"""Explicit configuration, strict accounting, task schema; no implicit model fallback."""

from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
import tiktoken

ROOT = Path(__file__).resolve().parents[3]
ENC = tiktoken.get_encoding("cl100k_base")
ARMS = ("agent", "rag", "pack")


class IntegrityError(RuntimeError):
    pass


class TransportError(RuntimeError):
    pass


class SpendingPause(RuntimeError):
    pass


def digest_bytes(b):
    return hashlib.sha256(b).hexdigest()


def digest_file(path):
    return digest_bytes(Path(path).read_bytes())


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(obj):
    return digest_bytes(canonical(obj).encode())


def tokens(text):
    return len(ENC.encode(text, disallowed_special=()))


def clip(text, cap):
    if cap <= 0:
        return ""
    if tokens(text) <= cap:
        return text
    marker = " [TRUNCATED]"
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + marker
        if tokens(candidate) <= cap:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def read_config(path):
    cfg = json.loads(Path(path).read_text())
    if cfg.get("version") != 4 or cfg.get("agent_interface") != "pi-native-v1":
        raise ValueError("Explicit native Agent interface required")
    if (
        not cfg["arms"]
        or len(set(cfg["arms"])) != len(cfg["arms"])
        or set(cfg["arms"]) - set(ARMS)
    ):
        raise ValueError("Unknown, repeated or empty arms")
    if (cfg["provider"], cfg["model"], cfg["thinking"]) != (
        "deepseek",
        "deepseek-v4-pro",
        "high",
    ):
        raise ValueError("Model identity must be explicit DeepSeek V4 Pro high")
    for key in (
        "repeats",
        "budget_a",
        "chunk_lines",
        "max_tool_calls",
        "max_turns",
        "turn_timeout",
    ):
        if type(cfg[key]) is not int or cfg[key] <= 0:
            raise ValueError(key)
    if not 0 <= cfg["chunk_overlap"] < cfg["chunk_lines"]:
        raise ValueError("chunk_overlap")
    if cfg["max_turns"] < cfg["max_tool_calls"] + 1:
        raise ValueError("max_turns")
    if not math.isfinite(cfg["spending_pause_usd"]) or cfg["spending_pause_usd"] <= 0:
        raise ValueError("spending guard")
    return cfg


def load_rows(cfg):
    rows = [
        r
        for r in csv.DictReader((ROOT / cfg["sample_manifest"]).open())
        if r["role"] == cfg["role"]
    ]
    ids = cfg.get("entry_ids")
    if ids:
        by = {r["entry_id"]: r for r in rows}
        if len(set(ids)) != len(ids) or set(ids) - by.keys():
            raise ValueError("entry_ids")
        rows = [by[e] for e in ids]
    if not rows:
        raise ValueError("Empty manifest selection")
    if len({r["entry_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate entries")
    return rows


# Ground truth fields never exist in Task passed to methods or model.
def public_task(row):
    return {
        k: row[k]
        for k in (
            "entry_id",
            "report_id",
            "project",
            "repo_url",
            "commit",
            "vuln_title",
            "task_description",
        )
    }


def task_text(task):
    return (
        "## Vulnerability advisory\nTitle: "
        + task["vuln_title"]
        + "\n\nDescription:\n"
        + task["task_description"]
        + "\n\nIdentify the most likely vulnerable code locations."
    )


SYSTEM = (
    "You are an expert security analyst performing repository-level vulnerability localization. "
    "Given a vulnerability advisory and repository context, identify up to 5 likely vulnerable files. "
    'Reply with only one JSON object: {"candidate_files":[{"path":"repository-relative path",'
    '"line_start":1,"line_end":10,"reason":"brief reason"}],"notes":"optional"}. '
    "Use positive integer line numbers with line_start <= line_end. Do not write or execute code."
)
TOOLS = (
    '\nYou may instead reply with one JSON object {"tool":"name","args":{...}}. '
    'Tools: list_dir {"path":"directory"}; grep {"pattern":"POSIX extended regex",'
    '"glob":"optional file glob"}; read_file {"path":"file","start_line":1,"end_line":100}. '
    "Only eligible source files are accessible. Tool results and final answers must use repository-relative paths."
)


def parse(text):
    from protocol import decode

    return decode(text)[0]


class Ledger:
    def __init__(self, cap):
        self.cap = cap
        self.used = 0
        self.blocks = []

    @property
    def remaining(self):
        return self.cap - self.used

    def metadata(self, text, kind, cap=None):
        text = clip(
            "\n\n" + text,
            min(self.remaining, cap if cap is not None else self.remaining),
        )
        return self._record(text, kind, [])

    def code(self, path, lines, start, kind, cap=None):
        limit = min(self.remaining, cap if cap is not None else self.remaining)
        header = f"\n\n===== {path} =====\n"
        if not lines or tokens(header) > limit:
            return ""
        numbered = [f"{start+i}: {line}" for i, line in enumerate(lines)]
        full = header + "\n".join(numbered)
        if tokens(full) <= limit:
            text = full
            count = len(lines)
        else:
            lo, hi, count = 0, len(lines), 0
            while lo <= hi:
                mid = (lo + hi) // 2
                value = header + "\n".join(numbered[:mid]) + "\n[TRUNCATED]"
                if tokens(value) <= limit:
                    count = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if count == 0:
                return ""  # Never label a partial line as fully delivered.
            text = header + "\n".join(numbered[:count]) + "\n[TRUNCATED]"
        return self._record(
            text, kind, [{"path": path, "start": start, "end": start + count - 1}]
        )

    def _record(self, text, kind, spans):
        n = tokens(text)
        if n > self.remaining:
            raise IntegrityError("Repository budget overflow")
        if text:
            self.used += n
            self.blocks.append(
                {
                    "kind": kind,
                    "text": text,
                    "sha256": digest_bytes(text.encode()),
                    "tokens": n,
                    "spans": spans,
                }
            )
        return text
