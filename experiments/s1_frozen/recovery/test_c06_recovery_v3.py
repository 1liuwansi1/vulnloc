"""Offline checks of paid-call exclusion, provenance and sleep/billing guards."""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import c06_recovery_v3 as r
from billing import inspect_journal


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def seed(self, pending=False):
        parent = self.root / "parent"
        parent.mkdir()
        out = self.root / "child"
        out.mkdir()
        rows = [
            {"entry_id": "entry-a", "arm": "agent", "repeat": 1, "run_id": "parent", "failure_category": "invalid_json", "answer": None, "reported_cost_usd": .1},
            {"entry_id": "entry-a", "arm": "rag", "repeat": 1, "run_id": "parent", "failure_category": None, "answer": {"candidate_files": []}, "reported_cost_usd": .2},
            {"entry_id": "entry-a", "arm": "pack", "repeat": 1, "run_id": "parent", "failure_category": "transport_error", "answer": None, "reported_cost_usd": .3},
        ]
        rows[0]["recovery_origin"] = {"run_id":"grandparent", "record_index":0, "record_sha256":"fixture"}
        if pending:
            rows[-1]["reported_cost_usd"] = 0
        units = []
        calls = []
        for i, row in enumerate(rows):
            for state in ["started", "recorded"]:
                units.append({"unit": list(r.key(row)), "state": state})
            calls += [{"id": str(i), "state": "started", "unit": {k:row[k] for k in ["entry_id", "arm", "repeat"]}}, {"id": str(i), "state": "finished", "cost_usd": row["reported_cost_usd"]}]
            (parent / ("__".join(map(str, r.key(row))) + ".events.jsonl")).write_text("evidence\n")
        if pending:
            calls = calls[:-1]
        for name, values in [("records.jsonl", rows), ("unit_journal.jsonl", units), ("call_journal.jsonl", calls)]:
            (parent / name).write_text("".join(json.dumps(e)+"\n" for e in values))
        (parent / "execution_summary.json").write_text("stopped")
        plan = {"import_count": 2, "retry_units": [list(r.key(rows[-1]))], "recovery_code": {n:r.digest_file(r.ROOT/n) for n in r.RECOVERY_FILES}}
        before = r.inventory(parent)
        imported = r.seed_child(parent, out, {}, plan, "child")
        self.assertEqual(before, r.inventory(parent))
        return parent, out, plan, imported

    def test_unsettled_parent_charge_is_not_closed_or_reused(self):
        parent, out, plan, imported = self.seed(pending=True)
        self.assertEqual(len(inspect_journal(parent/"call_journal.jsonl")["pending"]), 1)
        self.assertEqual(inspect_journal(out/"call_journal.jsonl")["pending"], [])
        self.assertAlmostEqual(inspect_journal(out/"call_journal.jsonl")["known_cost_usd"], .3)
        self.assertTrue((parent/"entry-a__pack__1.events.jsonl").exists())
        self.assertEqual(imported[0]["recovery_origin"]["prior_origin"]["run_id"], "grandparent")

    def test_model_failure_imported_and_only_infrastructure_retried(self):
        parent, out, plan, imported = self.seed()
        self.assertEqual(len(imported), 2)
        self.assertEqual(imported[0]["failure_category"], "invalid_json")
        self.assertNotIn(tuple(plan["retry_units"][0]), {r.key(x) for x in imported})
        self.assertAlmostEqual(inspect_journal(out/"call_journal.jsonl")["known_cost_usd"], .3)
        self.assertFalse((out/"entry-a__pack__1.events.jsonl").exists())
        self.assertTrue((parent/"entry-a__pack__1.events.jsonl").exists())

    def test_refuses_existing_child(self):
        parent, out, plan, imported = self.seed()
        with self.assertRaises(r.IntegrityError):
            r.seed_child(parent, out, {}, plan, "child")

    def test_import_tampering_rejected(self):
        parent, out, plan, imported = self.seed()
        imported[0]["answer"] = {"candidate_files": [{"path": "invented.py"}]}
        (out/"records.jsonl").write_text("".join(json.dumps(e)+"\n" for e in imported))
        with self.assertRaises(r.IntegrityError):
            r.verify_imports(out, parent, plan)

    def test_duplicate_recovered_unit_rejected(self):
        parent, out, plan, imported = self.seed()
        with (out/"records.jsonl").open("a") as f:
            f.write(json.dumps(imported[0])+"\n")
        with self.assertRaises(r.IntegrityError):
            r.verify_imports(out, parent, plan)

    def test_paid_history_missing_rejected(self):
        parent, out, plan, imported = self.seed()
        (out/"call_journal.jsonl").unlink()
        with self.assertRaises(r.IntegrityError):
            r.runner.verify_run_history(out, {r.key(x) for x in imported})

    def test_partial_record_tail_rejected(self):
        p=self.root/"tail.jsonl"
        p.write_text("{}")
        with self.assertRaises(r.IntegrityError):
            r.read_lines(p)

    def test_awake_heartbeat_conditions(self):
        p=self.root/"awake.json"
        for state, age, required in [("released",0,False),("active",100,True),("active",-100,True)]:
            p.write_text(json.dumps({"state":state,"unix_time":time.time()-age,"system_required":required}))
            with self.assertRaises(r.IntegrityError):
                r.heartbeat(p)
        p.write_text(json.dumps({"state":"active","unix_time":time.time(),"system_required":True}))
        r.heartbeat(p)

    def test_small_future_heartbeat_accepted(self):
        p=self.root/"awake-future.json"
        for skew in [.001, .5, 2.0]:
            p.write_text(json.dumps({"state":"active","unix_time":time.time()+skew,"system_required":True}))
            r.heartbeat(p)

    def guarded(self, extra=.3, operating_guard=None):
        import native_bridge
        base=r.runner.Spending
        old_handle=native_bridge.NativeBridge.handle
        self.addCleanup(setattr, r.runner, "Spending", base)
        self.addCleanup(setattr, native_bridge.NativeBridge, "handle", old_handle)
        awake=self.root/"awake.json"
        awake.write_text(json.dumps({"state":"active","unix_time":time.time(),"system_required":True}))
        r.install_guards(awake,extra,operating_guard)
        return r.runner.Spending(self.root,{"spending_pause_usd":1},False)

    def test_guard_includes_superseded_attempt_cost(self):
        spend=self.guarded(.3)
        spend.total=.7
        with self.assertRaises(r.SpendingPause):
            spend.before()
        self.assertFalse(spend.path.exists())

    def test_explicit_operating_cap_without_changing_scientific_config(self):
        spend=self.guarded(.3,1.2)
        self.assertEqual(spend.pause,1.2)
        spend.total=.7
        spend.unit={"entry_id":"a","arm":"rag","repeat":1}
        spend.before()
        spend.after({"cost_available":True,"cost":.3})
        with self.assertRaises(r.SpendingPause):
            spend.before()

    def test_error_response_not_closed_as_free_request(self):
        spend=self.guarded()
        spend.unit={"entry_id":"a","arm":"rag","repeat":1}
        spend.before()
        with self.assertRaises(r.IntegrityError):
            spend.after({"provider_error":True,"cost_available":True,"cost":0})
        self.assertEqual(len(inspect_journal(spend.path)["pending"]),1)

    def test_native_error_placeholder_stays_unknown(self):
        import native_bridge
        spend=self.guarded()
        spend.unit={"entry_id":"a","arm":"agent","repeat":1}
        spend.before()
        bridge=object.__new__(native_bridge.NativeBridge)
        bridge.spending=spend
        bridge.audit_path=self.root/"native.jsonl"
        with self.assertRaises(r.IntegrityError):
            bridge.handle({"op":"after_request","message":{"stopReason":"error","errorMessage":"Connection error.","usage":{"cost":{"total":0}}}})
        self.assertEqual(len(inspect_journal(spend.path)["pending"]),1)
        self.assertEqual(r.read_lines(bridge.audit_path)[0]["billing_status"],"UNKNOWN")

    def test_guard_keeps_normal_cost_and_unique_request_identity(self):
        spend=self.guarded()
        spend.unit={"entry_id":"a","arm":"rag","repeat":1}
        spend.before()
        spend.after({"cost_available":True,"cost":.2})
        report=inspect_journal(spend.path)
        self.assertEqual(report["pending"],[])
        self.assertEqual(report["known_cost_usd"],.2)


if __name__ == "__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if os.environ.get("RESULTS_DIR"):
        out=Path(os.environ["RESULTS_DIR"])
        for name in r.RECOVERY_FILES+["06_experiments/scripts/test_c06_recovery_v3.py"]:
            target=out/"implementation"/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((r.ROOT/name).read_bytes())
        (out/"checks.json").write_text(json.dumps({"evidence":"NOT_RESEARCH_DATA","checks":result.testsRun,"all_pass":result.wasSuccessful(),"paid_calls":0,"errors":len(result.errors),"failures":len(result.failures)}))
    sys.exit(0 if result.wasSuccessful() else 1)
