"""Regression and adversarial checks for the observed protocol/lifecycle incident."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core import ROOT, parse, IntegrityError, TransportError
from protocol import decode
from runner import Spending
from methods import Session
from transport import PiRpcLLM
from billing import inspect_journal


class RepairTests(unittest.TestCase):
    def test_duplicate_billing_finish_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            events = [
                {"id": "x", "state": "started"},
                {"id": "x", "state": "finished", "cost_usd": 0.1},
            ]
            path.write_text("\n".join(map(json.dumps, events + [events[1]])))
            with self.assertRaises(IntegrityError):
                inspect_journal(path)

    def test_orphan_or_unknown_billing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            for event in (
                {"id": "x", "state": "finished", "cost_usd": 0},
                {"id": "x", "state": "resolved"},
            ):
                path.write_text(json.dumps(event))
                with self.assertRaises(IntegrityError):
                    inspect_journal(path)

    def test_unknown_historical_call_remains_explicit(self):
        report = inspect_journal(
            ROOT
            / "07_results/raw/c06-revision-formal-20261003T144840Z-7e5d/call_journal.jsonl"
        )
        self.assertEqual(
            (report["started"], report["finished"], len(report["pending"])), (29, 28, 1)
        )
        self.assertAlmostEqual(report["known_cost_usd"], 1.27124668)

    def test_all_observed_failed_messages(self):
        raw = (
            ROOT
            / "07_results/raw/c06-revision-formal-20261003T144840Z-7e5d/records.jsonl"
        )
        accepted = rejected = 0
        for record in map(json.loads, raw.read_text().splitlines()):
            if record["arm"] != "agent":
                continue
            for call in record["calls"]:
                text = call["response"]["text"]
                obj, label = decode(text)
                if "<arg_key>" in text:
                    self.assertIsNone(obj)  # No tool name: do not guess.
                    rejected += 1
                else:
                    self.assertEqual(
                        obj,
                        {
                            "tool": "list_dir",
                            "args": {"path": "./" if '"./"' in text else "."},
                        },
                    )
                    accepted += 1
        self.assertEqual((accepted, rejected), (13, 1))

    def test_xml_parameters_typed(self):
        self.assertEqual(
            parse(
                '<tool_calls><invoke name="read_file"><parameter name="path">src/a.py</parameter><parameter name="start_line">2</parameter><parameter name="end_line">9</parameter></invoke></tool_calls>'
            ),
            {
                "tool": "read_file",
                "args": {"path": "src/a.py", "start_line": 2, "end_line": 9},
            },
        )

    def test_final_wrapped_json(self):
        value = {"candidate_files": [{"path": "a.py", "line_start": 2, "line_end": 4}]}
        self.assertEqual(
            parse("<tool_call>" + json.dumps(value) + "</tool_call>")[
                "candidate_files"
            ],
            value["candidate_files"],
        )

    def test_negative_payloads(self):
        samples = [
            'Here is a tool: {"tool":"list_dir","args":{}}',
            '{"tool":"list_dir","args":{}} {"tool":"read_file","args":{"path":"a.py"}}',
            '<tool name="list_dir"/><tool name="grep"/>',
            '<tool name="bash"><parameter name="command">echo BAD</parameter></tool>',
            '<tool name="list_dir"><parameter name="path">.</parameter><parameter name="path">..</parameter></tool>',
            '<tool name="read_file"><parameter name="path">a.py</parameter><parameter name="start_line">1.5</parameter></tool>',
            '<!DOCTYPE tool [<!ENTITY a SYSTEM "file:///etc/passwd">]><tool name="list_dir"><parameter name="path">&a;</parameter></tool>',
            '<tool name="list_dir"><parameter name="path"><nested/></parameter></tool>',
            '<tool name="list_dir"><parameter name="path">.</parameter>prose</tool>',
            '<tool_call>{"tool":"list_dir","args":{}}</tool_call> trailing',
            '{"tool":"list_dir","tool":"grep","args":{}}',
            '{"tool":"grep","args":{"pattern":7}}',
            '{"tool":"read_file","args":{"path":"a.py","start_line":true}}',
            '{"tool":"read_file","args":{"path":"a.py","start_line":9,"end_line":1}}',
            '{"tool":"list_dir","args":{"command":"arbitrary"}}',
            '{"tool":"list_dir","args":{},"candidate_files":[]}',
            '```json\n{"candidate_files":[]}\n``` trailing',
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertIsNone(parse(sample))

    def test_size_limit(self):
        self.assertIsNone(parse(" " * 1_000_001))

    def fixture(self, events):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        worker = Path(self.tmp.name) / "worker.py"
        worker.write_text(
            "import sys,json,time\nfor line in sys.stdin:\n time.sleep(.03)\n for event in "
            + repr(events)
            + ": print(json.dumps(event),flush=True)\n"
        )
        client = PiRpcLLM(
            "fixture", pi_bin=[sys.executable, str(worker)], turn_timeout=2
        )
        self.addCleanup(client.close)
        return client

    def end(self, cost=0.01, provider="deepseek"):
        return {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "provider": provider,
                "model": "deepseek-v4-pro",
                "usage": {"input": 10, "output": 2, "cost": {"total": cost}},
                "content": [{"type": "text", "text": '{"candidate_files":[]}'}],
            },
        }

    def test_forward_wall_jump_does_not_timeout(self):
        client = self.fixture([self.end(), {"type": "agent_settled"}])
        with patch("transport.time.time", side_effect=[1000, 100000]):
            response = client.prompt("test")
        self.assertFalse(response["timed_out"])
        self.assertTrue(response["cost_available"])
        self.assertGreater(response["wall_elapsed_seconds"], 600)
        self.assertLess(response["active_elapsed_seconds"], 2)

    def test_backward_wall_jump_does_not_extend_deadline(self):
        client = self.fixture([])
        client.turn_timeout = 0.08
        with patch("transport.time.time", side_effect=[100000, 1000]):
            response = client.prompt("test")
        self.assertTrue(response["timed_out"])
        self.assertLess(response["active_elapsed_seconds"], 0.5)
        self.assertFalse(response["cost_available"])

    def test_identity_of_every_completion(self):
        client = self.fixture(
            [self.end(provider="wrong"), self.end(), {"type": "agent_settled"}]
        )
        spend = Spending(Path(self.tmp.name), {"spending_pause_usd": 5}, False)
        with self.assertRaises(TransportError):
            Session(client, spend).ask("test")
        self.assertEqual(spend.total, 0.02)  # Rejected responses still billed.

    def test_missing_identity_is_not_accepted_real(self):
        event = self.end()
        event["message"].pop("model")
        client = self.fixture([event, {"type": "agent_settled"}])
        with self.assertRaises(TransportError):
            Session(
                client, Spending(Path(self.tmp.name), {"spending_pause_usd": 5}, False)
            ).ask("test")

    def test_retry_negative_cost_cannot_cancel_positive(self):
        client = self.fixture(
            [self.end(-0.01), self.end(0.02), {"type": "agent_settled"}]
        )
        response = client.prompt("test")
        self.assertFalse(response["cost_available"])

    def test_billing_missing_one_completion_is_unknown(self):
        event = self.end()
        event["message"]["usage"].pop("cost")
        client = self.fixture([event, self.end(), {"type": "agent_settled"}])
        spend = Spending(Path(self.tmp.name), {"spending_pause_usd": 5}, False)
        with self.assertRaises(IntegrityError):
            Session(client, spend).ask("test")
        with self.assertRaises(IntegrityError):
            Spending(Path(self.tmp.name), {"spending_pause_usd": 5}, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
