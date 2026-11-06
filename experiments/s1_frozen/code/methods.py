"""Three explicit acquisition policies sharing one authorization and line renderer."""

import fnmatch, subprocess, tempfile, time
from pathlib import PurePosixPath
from core import (
    IntegrityError,
    TransportError,
    SpendingPause,
    Ledger,
    parse,
    task_text,
    tokens,
)
from protocol import decode
import index


class Session:
    def __init__(self, llm, spending):
        self.llm = llm
        self.spending = spending
        self.calls = []

    def ask(self, text):
        managed = getattr(self.llm, "billing_managed", False)
        if not managed:
            self.spending.before()
        response = self.llm.prompt(text)
        self.calls.append({"user": text, "response": response})
        if managed:
            bridge = self.llm.native_bridge
            if bridge.fatal is not None:
                raise bridge.fatal
            if self.spending.pending_id is not None:
                raise IntegrityError("Native prompt ended with unresolved billing")
        else:
            self.spending.after(response)
        observed = response.get("observed", {})
        if not self.spending.mock and (
            observed != {"provider": "deepseek", "model": "deepseek-v4-pro"}
            or any(
                item != observed
                for item in response.get("observed_messages", [observed])
            )
        ):
            raise TransportError("Missing or inconsistent observed model identity")
        if observed.get("provider") not in (None, "deepseek") or observed.get(
            "model"
        ) not in (None, "deepseek-v4-pro"):
            raise TransportError(
                "Observed provider/model identity differs from request"
            )
        if (
            response.get("provider_error")
            or response.get("timed_out")
            or response.get("crashed")
            or not response.get("saw_message_end", False)
        ):
            raise TransportError(
                response.get("error") or "Incomplete/failed provider turn"
            )
        response["protocol_format"] = decode(response["text"])[1]
        return response["text"]


def tool(name, args, u, ledger, cfg):
    try:
        if name == "list_dir":
            path = str(PurePosixPath(str(args.get("path", "."))))
            listing = u.listing(path)[:200]
            return ledger.metadata(
                "Directory " + path + "\n" + "\n".join(listing), "list", 4000
            )
        if name == "read_file":
            path = str(args.get("path", ""))
            lines = u.read(path)
            start = args.get("start_line", 1)
            end = args.get("end_line", len(lines))
            if (
                type(start) is not int
                or type(end) is not int
                or start < 1
                or end < start
            ):
                raise ValueError("Invalid line range")
            return (
                ledger.code(
                    path, lines[start - 1 : min(end, start + 399)], start, "read", 8000
                )
                or "[no complete line fits remaining budget]"
            )
        if name == "grep":
            pattern = str(args.get("pattern", ""))
            glob = str(args.get("glob", "*"))
            if not pattern or len(pattern) > 2000:
                raise ValueError("Invalid regex")
            paths = [
                p
                for p in u.files
                if fnmatch.fnmatch(p, glob)
                or fnmatch.fnmatch(PurePosixPath(p).name, glob)
            ]
            pieces = []
            count = 0
            started = time.monotonic()
            matched = False
            for offset in range(0, len(paths), 128):
                batch = paths[offset : offset + 128]
                # Authorize exact manifest paths BEFORE search, never broad recursive grep then filtering.
                for p in batch:
                    u.read(p)
                with tempfile.TemporaryFile(mode="w+") as out:
                    res = subprocess.run(
                        ["grep", "-nHE", "-m", "50", "-e", pattern, "--", *batch],
                        cwd=u.root,
                        stdout=out,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=max(0.1, 30 - (time.monotonic() - started)),
                    )
                    if res.returncode not in (0, 1):
                        raise ValueError("Invalid grep expression")
                    out.seek(0)
                    for line in out:
                        # Parse against known authorized path prefixes, supporting colons in filenames.
                        path = next(
                            (p for p in batch if line.startswith(p + ":")), None
                        )
                        if path is None:
                            raise IntegrityError("Unexpected search output path")
                        number = int(line[len(path) + 1 :].split(":", 1)[0])
                        content = u.read(path)
                        begin = max(1, number - 2)
                        end = min(len(content), number + 2)
                        value = ledger.code(
                            path,
                            content[begin - 1 : end],
                            begin,
                            "grep",
                            min(
                                4000 - sum(tokens(x) for x in pieces), ledger.remaining
                            ),
                        )
                        if value:
                            pieces.append(value)
                            matched = True
                        count += 1
                        if (
                            count >= 50
                            or ledger.remaining <= 0
                            or sum(tokens(x) for x in pieces) >= 4000
                        ):
                            break
                if (
                    count >= 50
                    or ledger.remaining <= 0
                    or sum(tokens(x) for x in pieces) >= 4000
                ):
                    break
                if time.monotonic() - started >= 30:
                    raise TimeoutError("Local grep deadline")
            return (
                "".join(pieces)
                if matched
                else ledger.metadata(
                    "(no matches in eligible source files)", "grep_empty", 4000
                )
            )
        raise ValueError("Unknown tool")
    except (PermissionError, ValueError, TimeoutError, subprocess.TimeoutExpired) as ex:
        return ledger.metadata("[tool error: " + str(ex) + "]", "tool_error", 500)


def acquire_pack(u, ledger):
    tree = "\n".join(u.files)
    parts = [ledger.metadata("Eligible source paths:\n" + tree, "tree", 5000)]
    for path in u.files:
        if ledger.remaining <= 0:
            break
        part = ledger.code(path, u.read(path), 1, "pack")
        if part:
            parts.append(part)
    return "".join(parts)


def acquire_rag(u, ledger, cfg, embedder, mock):
    cs, v, _ = index.load(u, cfg, mock)
    # Query is supplied separately from the task-blind index.
    return cs, v


def finish(session, user):
    for correction in range(2):
        text = session.ask(user)
        if not text.strip():
            return None, "empty_answer"
        obj = parse(text)
        if obj is not None and "candidate_files" in obj:
            return obj, None
        user = 'Reply with ONLY the final JSON object {"candidate_files":[...]}; at most five files and valid positive integer line ranges.'
    return None, "invalid_json"


def run(arm, task, u, cfg, session, embedder=None, mock=False):
    if arm not in ("agent", "rag", "pack"):
        raise ValueError("Unknown arm: " + arm)
    ledger = Ledger(cfg["budget_a"])
    if arm == "agent" and getattr(session.llm, "native_tools", False):
        bridge = session.llm.native_bridge
        session.ledger = bridge.ledger
        answer, failure = finish(session, task_text(task))
        return {
            "answer": answer,
            "failure_category": failure,
            "blocks": bridge.ledger.blocks,
            "A": bridge.ledger.used,
            "trajectory": bridge.trajectory,
            "native_provider_requests": bridge.requests,
        }
    session.ledger = ledger
    trajectory = []
    if arm == "pack":
        context = acquire_pack(u, ledger)
        answer, failure = finish(
            session, task_text(task) + "\n\n## Repository context" + context
        )
    elif arm == "rag":
        cs, v = acquire_rag(u, ledger, cfg, embedder, mock)
        query = task["vuln_title"] + "\n" + task["task_description"]
        parts = []
        for i in index.rank(cs, v, query, embedder):
            c = cs[i]
            value = ledger.code(c["path"], c["text"].splitlines(), c["start"], "rag")
            if value:
                parts.append(value)
            if ledger.remaining <= 0:
                break
        answer, failure = finish(
            session, task_text(task) + "\n\n## Repository context" + "".join(parts)
        )
    elif arm == "agent":
        message = task_text(task)
        corrected = False
        answer = None
        failure = "budget_exhausted_no_final"
        forced = False
        for _ in range(cfg["max_turns"]):
            text = session.ask(message)
            if not text.strip():
                failure = "empty_answer"
                break
            obj = parse(text)
            if obj is not None and "candidate_files" in obj:
                answer = obj
                failure = None
                break
            if obj is not None and "tool" in obj:
                corrected = False
                if len(trajectory) >= cfg["max_tool_calls"] or ledger.remaining <= 0:
                    if forced:
                        break
                    message = "[BUDGET EXHAUSTED: provide final answer JSON now]"
                    forced = True
                    continue
                value = tool(obj["tool"], obj["args"], u, ledger, cfg)
                trajectory.append(obj)
                message = "[tool result]" + value
                continue
            if corrected:
                failure = "invalid_json"
                break
            corrected = True
            message = 'Reply with only a valid tool JSON or final {"candidate_files":[...]} JSON.'
    else:
        raise ValueError("Unknown arm: " + arm)
    return {
        "answer": answer,
        "failure_category": failure,
        "blocks": ledger.blocks,
        "A": ledger.used,
        "trajectory": trajectory,
    }
