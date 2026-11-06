"""Native bridge boundary, billing and resume-artifact regressions."""

import json
import socket
import tempfile
import unittest
from pathlib import Path
from core import (
    ROOT,
    IntegrityError,
    TransportError,
    canonical,
    digest_file,
    read_config,
)
from source import Universe
from runner import Spending, verify_resume_artifacts
from native_bridge import NativeBridge
from methods import Session, run

CFG = read_config(ROOT / "06_experiments/c06_repair/development.json")


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        (self.root / "a.py").write_text("needle = 1\nvalue = needle\n")
        (self.root / "dist").mkdir()
        (self.root / "dist/no.py").write_text("private = 1\n")
        self.u = Universe.scan(self.root)
        self.spending = Spending(Path(self.tmp.name), CFG, False)
        self.bridge = NativeBridge(
            self.u, CFG, self.spending, Path(self.tmp.name) / "native.jsonl"
        )

    def tearDown(self):
        self.bridge.close()
        self.tmp.cleanup()

    def end(self, cost=0.01):
        return {
            "op": "after_request",
            "message": {
                "role": "assistant",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "usage": {"cost": {"total": cost}},
            },
        }

    def ipc(self, request):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(self.bridge.socket)
            conn.sendall((canonical(request) + "\n").encode())
            with conn.makefile() as stream:
                return json.loads(stream.readline())

    def test_real_ipc_roundtrip(self):
        response = self.ipc(
            {
                "op": "tool",
                "id": "a",
                "name": "read_file",
                "args": {"path": "a.py", "start_line": 1, "end_line": 2},
            }
        )
        self.assertTrue(response["ok"])
        self.assertIn("1: needle = 1", response["text"])
        self.assertEqual(len(self.bridge.trajectory), 1)

    def test_billing_each_request_and_no_double_charge(self):
        for _ in range(2):
            self.bridge.handle(
                {
                    "op": "before_request",
                    "tool_names": ["list_dir", "grep", "read_file"],
                }
            )
            self.bridge.handle(self.end())
        self.assertEqual(self.spending.total, 0.02)
        self.assertEqual(self.bridge.requests, 2)
        self.assertIsNone(self.spending.pending_id)

    def test_unknown_previous_request_blocks_next(self):
        self.bridge.handle(
            {"op": "before_request", "tool_names": ["list_dir", "grep", "read_file"]}
        )
        with self.assertRaises(IntegrityError):
            self.bridge.handle(
                {
                    "op": "before_request",
                    "tool_names": ["list_dir", "grep", "read_file"],
                }
            )
        self.assertEqual(self.bridge.requests, 1)

    def test_missing_native_cost_remains_pending(self):
        self.bridge.handle(
            {"op": "before_request", "tool_names": ["list_dir", "grep", "read_file"]}
        )
        message = self.end()
        message["message"]["usage"] = {}
        with self.assertRaises(IntegrityError):
            self.bridge.handle(message)
        self.assertIsNotNone(self.spending.pending_id)

    def test_duplicate_native_tool_cannot_execute_twice(self):
        request = {"op": "tool", "id": "x", "name": "list_dir", "args": {"path": "."}}
        self.bridge.handle(request)
        with self.assertRaises(IntegrityError):
            self.bridge.handle(request)
        self.assertEqual(len(self.bridge.trajectory), 1)

    def test_native_source_denial(self):
        for n, path in enumerate(("dist/no.py", "../other.py", "/etc/passwd")):
            response = self.bridge.handle(
                {
                    "op": "tool",
                    "id": str(n),
                    "name": "read_file",
                    "args": {"path": path},
                }
            )
            self.assertIn("tool error", response["text"])
            self.assertNotIn("private = 1", response["text"])

    def test_tool_budget_deactivates_tools(self):
        self.bridge.cfg = {**CFG, "max_tool_calls": 1}
        response = self.bridge.handle(
            {"op": "tool", "id": "x", "name": "list_dir", "args": {}}
        )
        self.assertTrue(response["exhausted"])
        response = self.bridge.handle(
            {"op": "tool", "id": "y", "name": "read_file", "args": {"path": "a.py"}}
        )
        self.assertTrue(response["exhausted"])
        self.assertEqual(len(self.bridge.trajectory), 1)

    def test_turn_limit_stops_before_new_billed_request(self):
        self.bridge.cfg = {**CFG, "max_turns": 1}
        self.bridge.handle(
            {"op": "before_request", "tool_names": ["list_dir", "grep", "read_file"]}
        )
        self.bridge.handle(self.end())
        with self.assertRaises(TransportError):
            self.bridge.handle(
                {
                    "op": "before_request",
                    "tool_names": ["list_dir", "grep", "read_file"],
                }
            )
        self.assertEqual(self.bridge.requests, 1)
        self.assertIsNone(self.spending.pending_id)

    def test_full_native_python_path_with_managed_billing(self):
        bridge = self.bridge

        class Fake:
            native_tools = billing_managed = True
            native_bridge = bridge

            def prompt(self, text):
                bridge.handle(
                    {
                        "op": "before_request",
                        "tool_names": ["list_dir", "grep", "read_file"],
                    }
                )
                bridge.handle(
                    {
                        "op": "tool",
                        "id": "request1",
                        "name": "read_file",
                        "args": {"path": "a.py"},
                    }
                )
                bridge.handle(Fixture.end())
                return {
                    "text": '{"candidate_files":[]}',
                    "cost_available": True,
                    "cost": 0.01,
                    "input": 4,
                    "output": 2,
                    "observed": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                    "saw_message_end": True,
                }

        Fixture = self
        result = run(
            "agent",
            {"vuln_title": "fixture", "task_description": "fixture"},
            self.u,
            CFG,
            Session(Fake(), self.spending),
        )
        self.assertIsNone(result["failure_category"])
        self.assertEqual(self.spending.total, 0.01)
        self.assertEqual(result["A"], self.bridge.ledger.used)

    def test_resume_missing_or_corrupt_artifact_rejected(self):
        out = self.root / "resume"
        out.mkdir()
        expected = {"code": {"code.py": "expected"}, "manifest_sha256": "expected"}
        with self.assertRaises(IntegrityError):
            verify_resume_artifacts(out, CFG, expected, None, None)
        (out / "config.json").write_text(canonical(CFG))
        (out / "implementation").mkdir()
        (out / "implementation/code.py").write_text("corrupt")
        with self.assertRaises(IntegrityError):
            verify_resume_artifacts(out, CFG, expected, None, None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
