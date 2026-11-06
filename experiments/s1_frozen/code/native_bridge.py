"""Native Pi tool IPC; the Python engine retains source authorization and budgets."""

import json
import math
import socketserver
import tempfile
import threading
from pathlib import Path
from core import Ledger, IntegrityError, TransportError, SpendingPause, ROOT, canonical
from protocol import validate


class NativeBridge:
    def __init__(self, universe, cfg, spending, audit_path):
        self.universe, self.cfg, self.spending = universe, cfg, spending
        self.ledger = Ledger(cfg["budget_a"])
        self.trajectory, self.requests, self.fatal = [], 0, None
        self.seen_ids = set()
        self.audit_path = Path(audit_path)
        self.extension_path = Path(__file__).parent / "native_tools.ts"
        self.tmp = tempfile.TemporaryDirectory(prefix="c06-native-")
        self.socket = str(Path(self.tmp.name) / "ipc.sock")
        self.lock = threading.Lock()
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(45)
                data = self.rfile.readline(1_000_001)
                try:
                    if len(data) > 1_000_000 or not data.endswith(b"\n"):
                        raise IntegrityError("Oversized or incomplete IPC message")
                    with bridge.lock:
                        result = bridge.handle(json.loads(data))
                    self.wfile.write(
                        (canonical({"ok": True, **result}) + "\n").encode()
                    )
                except Exception as error:
                    bridge.fatal = error
                    self.wfile.write(
                        (canonical({"ok": False, "error": str(error)}) + "\n").encode()
                    )

        self.server = socketserver.ThreadingUnixStreamServer(self.socket, Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def handle(self, request):
        from methods import tool
        from runner import append

        if self.fatal is not None:
            raise IntegrityError("Native bridge already stopped")
        op = request.get("op")
        if op == "before_request":
            names = request.get("tool_names")
            exhausted = (
                len(self.trajectory) >= self.cfg["max_tool_calls"]
                or self.ledger.remaining <= 0
            )
            if not isinstance(names, list) or (
                set(names) != {"list_dir", "grep", "read_file"}
                and not (not names and exhausted)
            ):
                raise IntegrityError(
                    "Actual provider tool declarations differ: " + repr(names)
                )
            if self.spending.pending_id is not None:
                raise IntegrityError("Previous native request remains unbilled")
            if self.requests >= self.cfg["max_turns"]:
                raise TransportError("Native turn limit reached")
            self.spending.before()
            self.requests += 1
            append(
                self.audit_path,
                {
                    "op": op,
                    "call_id": self.spending.pending_id,
                    "request_number": self.requests,
                    "tool_names": names,
                },
            )
            return {}
        if op == "after_request":
            message = request["message"]
            if message.get("role") != "assistant" or self.spending.pending_id is None:
                raise IntegrityError("Unexpected native completion")
            usage = message.get("usage") or {}
            cost = (usage.get("cost") or {}).get("total")
            response = {
                "cost": cost,
                "cost_available": type(cost) in (int, float)
                and math.isfinite(cost)
                and cost >= 0,
            }
            self.spending.after(response)
            self.spending.pending_id = None
            append(
                self.audit_path,
                {
                    "op": op,
                    "usage": usage,
                    "provider": message.get("provider"),
                    "model": message.get("model"),
                },
            )
            if (message.get("provider"), message.get("model")) != (
                "deepseek",
                "deepseek-v4-pro",
            ):
                raise TransportError("Native completion model identity differs")
            if message.get("stopReason") in ("error", "aborted") or message.get(
                "errorMessage"
            ):
                raise TransportError("Native provider completion failed")
            return {}
        if op != "tool":
            raise IntegrityError("Unknown bridge operation")
        call_id = request.get("id")
        if not isinstance(call_id, str) or call_id in self.seen_ids:
            raise IntegrityError("Duplicate or missing native tool call ID")
        self.seen_ids.add(call_id)
        if (
            len(self.trajectory) >= self.cfg["max_tool_calls"]
            or self.ledger.remaining <= 0
        ):
            return {
                "text": "[BUDGET EXHAUSTED: provide final answer JSON now]",
                "exhausted": True,
            }
        obj = validate({"tool": request.get("name"), "args": request.get("args")})
        if obj is None:
            raise IntegrityError("Invalid native tool schema")
        self.universe.verify()
        text = tool(obj["tool"], obj["args"], self.universe, self.ledger, self.cfg)
        self.trajectory.append(obj)
        exhausted = (
            len(self.trajectory) >= self.cfg["max_tool_calls"]
            or self.ledger.remaining <= 0
        )
        append(
            self.audit_path,
            {"op": op, "id": call_id, "tool": obj, "A": self.ledger.used, "text": text},
        )
        return {"text": text, "exhausted": exhausted}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()
