"""Explicit, auditable recovery of an interrupted run; frozen kernel is untouched.

Completed model outcomes (including format failures) are imported without retry.
Only declared infrastructure failures are attempted again in a new harness run.
The old raw data, metadata and billed attempts remain immutable evidence.
"""

import argparse
import fcntl
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "06_experiments/scripts/c06_repair"))
import runner
from core import IntegrityError, SpendingPause, canonical, digest_file, fingerprint, read_config
from preflight import validate
import yaml

INFRA = {"transport_error", "infrastructure_error", "spending_pause"}
RECOVERY_FILES = [
    "06_experiments/scripts/c06_recovery.py",
    "06_experiments/scripts/analyze_c06_recovery.py",
    "06_experiments/scripts/keep_c06_awake.ps1",
]


def require(value, message):
    if not value:
        raise IntegrityError(message)


def key(row):
    return (row["entry_id"], row["arm"], row["repeat"])


def read_lines(path):
    data = Path(path).read_bytes()
    require(not data or data.endswith(b"\n"), "Incomplete JSONL tail")
    return [json.loads(line) for line in data.splitlines()]


def inventory(folder):
    return {
        str(p.relative_to(folder)): digest_file(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != ".writer.lock"
    }


def check_parent(parent, cfg, launch, preflight):
    require(parent.parent == ROOT / "07_results/raw", "Parent must be a harness run")
    metadata_path = ROOT / "06_experiments/metadata" / (parent.name + ".yaml")
    metadata = yaml.safe_load(metadata_path.read_text())
    require(metadata["status"] == "failed", "Recovery parent must be stopped/failed")
    ident = runner.identity(cfg)
    contract = json.loads(launch.read_text())
    require(json.loads((parent / "identity.json").read_text()) == ident, "Parent version changed")
    require(contract["identity"] == ident, "Launch identity changed")
    require(not contract["mock"], "Recovery expects real data")
    validate(json.loads(preflight.read_text()), cfg, launch)
    runner.verify_resume_artifacts(parent, cfg, ident, contract, preflight)
    records = read_lines(parent / "records.jsonl")
    require(records and all(r["run_id"] == parent.name and not r["mock"] for r in records), "Wrong parent records")
    require([key(r) for r in records] == [key(r) for r in contract["schedule"][:len(records)]], "Parent is not a unique schedule prefix")
    require(json.loads((parent / "schedule.json").read_text()) == contract["schedule"], "Schedule changed")
    runner.verify_run_history(parent, {key(r) for r in records})
    failed = [r for r in records if r["failure_category"] in INFRA]
    require(len(failed) == 1 and failed[0] is records[-1], "Only one terminal infrastructure incident is supported")
    require(failed[0]["failure_category"] == "transport_error", "Other infrastructure failures need diagnosis")
    for r in records:
        require(all(r[n] == cfg[n] for n in ["provider", "model", "thinking"]), "Model identity changed")
        require(sum(b["tokens"] for b in r["blocks"]) == r["A"] <= cfg["budget_a"], "Parent repository budget differs")
    return records, metadata_path


def make_plan(parent, cfg, launch, preflight):
    records, metadata_path = check_parent(parent, cfg, launch, preflight)
    failed = records[-1]
    prefix = "__".join(map(str, key(failed)))
    events = read_lines(parent / (prefix + ".events.jsonl"))
    errors = [e.get("message", {}) for e in events if e.get("message", {}).get("errorMessage")]
    require(any("Connection error" in m["errorMessage"] for m in errors), "Terminal connection failure evidence missing")
    calls = read_lines(parent / "call_journal.jsonl")
    failed_ids = [e["id"] for e in calls if e["state"] == "started" and key(e["unit"]) == key(failed)]
    require(failed_ids, "Failed attempt has no request history")
    return {
        "version": 1,
        "authorization": "User explicitly requested: 修复实验，继续运行 (2026-10-05).",
        "parent_run_id": parent.name,
        "parent_sha256": inventory(parent),
        "parent_metadata_sha256": digest_file(metadata_path),
        "config_sha256": fingerprint(cfg),
        "launch": str(launch.relative_to(ROOT)),
        "preflight": str(preflight.relative_to(ROOT)),
        "recovery_code": {n: digest_file(ROOT / n) for n in RECOVERY_FILES},
        "import_count": len(records) - 1,
        "planned_total": 720,
        "retry_units": [list(key(failed))],
        "preserve_model_failures": True,
        "failed_attempt_reported_cost_usd": failed["reported_cost_usd"],
        "historical_error_billing": {
            "call_id": failed_ids[-1],
            "status": "UNKNOWN",
            "reason": "Pi connection-error usage defaults to zero; it is not a verified zero supplier bill. Original journal is retained unchanged.",
        },
        "retry_policy": "Exactly one explicit recovery attempt for the declared terminal transport failure; no retries of model-output failures; any new infrastructure failure stops.",
        "cost_policy": "The original $60 guard includes the failed attempt reported cost. Unknown supplier charges remain separate and are never claimed as zero.",
        "guard_policy": "Windows SYSTEM_REQUIRED request with heartbeat, released on pipeline exit. All new paid calls require a recent heartbeat.",
    }


def validate_plan(plan, parent, cfg, launch, preflight):
    require(plan == make_plan(parent, cfg, launch, preflight), "Recovery plan or source evidence changed")


def seed_child(parent, out, cfg, plan, child_id):
    require(not any(out.iterdir()), "Refusing to overwrite or resume an existing recovery child")
    records = read_lines(parent / "records.jsonl")
    failed_key = tuple(plan["retry_units"][0])
    require(key(records[-1]) == failed_key, "Wrong retry unit")
    require(len(records) - 1 == plan["import_count"], "Wrong import count")
    failed_prefix = "__".join(map(str, failed_key))
    skip = {"records.jsonl", "call_journal.jsonl", "unit_journal.jsonl", "run_context.json", "execution_summary.json", ".writer.lock"}
    for p in parent.iterdir():
        if p.name in skip or p.name.startswith(failed_prefix + "."):
            continue
        dest = out / p.name
        if p.is_dir():
            shutil.copytree(p, dest)
        else:
            shutil.copyfile(p, dest)
    imported = []
    for i, row in enumerate(records[:-1]):
        value = dict(row)
        value["run_id"] = child_id
        value["recovery_origin"] = {"run_id": parent.name, "record_index": i, "record_sha256": fingerprint(row)}
        imported.append(value)
    (out / "records.jsonl").write_text("".join(canonical(r) + "\n" for r in imported))
    units = [e for e in read_lines(parent / "unit_journal.jsonl") if tuple(e["unit"]) != failed_key]
    calls = read_lines(parent / "call_journal.jsonl")
    included_ids = {e["id"] for e in calls if e["state"] == "started" and key(e["unit"]) != failed_key}
    calls = [e for e in calls if e["id"] in included_ids]
    for name, values in [("unit_journal.jsonl", units), ("call_journal.jsonl", calls)]:
        (out / name).write_text("".join(canonical(e) + "\n" for e in values))
    (out / "run_context.json").write_text(canonical({"run_id": child_id}))
    (out / "recovery_plan.json").write_text(canonical(plan))
    for name in RECOVERY_FILES:
        dest = out / "recovery_implementation" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    runner.verify_run_history(out, {key(r) for r in imported})
    verify_imports(out, parent, plan)
    return imported


def verify_imports(out, parent, plan):
    original = read_lines(parent / "records.jsonl")
    records = read_lines(out / "records.jsonl")
    require(len(records) >= plan["import_count"], "Imported records disappeared")
    child_id = json.loads((out / "run_context.json").read_text())["run_id"]
    for i, row in enumerate(records[:plan["import_count"]]):
        value = dict(row)
        origin = value.pop("recovery_origin", None)
        require(origin == {"run_id": parent.name, "record_index": i, "record_sha256": fingerprint(original[i])}, "Bad import provenance")
        require(value["run_id"] == child_id, "Wrong child identity")
        value["run_id"] = parent.name
        require(value == original[i], "An imported outcome changed")
    require(len(records) == len({key(r) for r in records}), "Duplicate recovery outcome")
    for row in records[plan["import_count"]:]:
        require("recovery_origin" not in row, "New result mislabelled as imported")
    for name, h in plan["recovery_code"].items():
        require(digest_file(ROOT / name) == h and digest_file(out / "recovery_implementation" / name) == h, "Recovery execution version changed")


def heartbeat(path):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        age = time.time() - state["unix_time"]
        require(state["state"] == "active" and state["system_required"] is True and 0 <= age < 90, "Keep-awake protection is stale/inactive")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise IntegrityError("Keep-awake protection unavailable") from e


def install_guards(path, historical_cost):
    base = runner.Spending

    class RecoverySpending(base):
        def before(self):
            heartbeat(path)
            if self.total + historical_cost >= self.pause:
                raise SpendingPause("Original and recovery reported costs reached the shared $60 guard")
            return super().before()

        def after(self, response):
            if any(response.get(k) for k in ["provider_error", "timed_out", "crashed"]):
                raise IntegrityError("Incomplete provider response; charge remains UNKNOWN")
            return super().after(response)

    runner.Spending = RecoverySpending
    # Error usage is a client placeholder, not supplier billing. Stop without
    # closing the pending journal; this accounting overlay changes no prompt/tool.
    import native_bridge
    original_handle = native_bridge.NativeBridge.handle

    def checked_handle(self, request):
        m = request.get("message", {})
        if request.get("op") == "after_request" and (m.get("stopReason") in ("error", "aborted") or m.get("errorMessage")):
            runner.append(self.audit_path, {"op": "provider_error_unbilled", "call_id": self.spending.pending_id, "error": m.get("errorMessage") or m.get("stopReason"), "billing_status": "UNKNOWN"})
            raise IntegrityError("Provider completion failed; its charge remains UNKNOWN")
        return original_handle(self, request)

    native_bridge.NativeBridge.handle = checked_handle
    return base, original_handle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--prepare-plan", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--awake-heartbeat")
    args = ap.parse_args()
    cfg = read_config(ROOT / "06_experiments/c06_repair/formal_proposal.json")
    parent = ROOT / "07_results/raw" / args.parent
    require(parent.parent == ROOT / "07_results/raw", "Invalid parent path")
    launch = ROOT / "06_experiments/c06_repair/freezes/f7362b60fc663bc81e9d806e9949340e2d3c0901820efd0d6ad20e6445984bcb.json"
    preflight = ROOT / "06_experiments/c06_repair/preflight-f7362b60.json"
    with (parent / ".writer.lock").open("a") as parent_lock:
        fcntl.flock(parent_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.prepare_plan:
            plan = make_plan(parent, cfg, launch, preflight)
            with (ROOT / args.plan).open("x") as f:
                f.write(canonical(plan))
            if os.environ.get("RESULTS_DIR"):
                (Path(os.environ["RESULTS_DIR"]) / "recovery_plan.json").write_text(canonical(plan))
            print(canonical({"status": "recovery_plan_prepared", "import_count": plan["import_count"], "retry_units": plan["retry_units"], "new_units": 720-plan["import_count"], "failed_attempt_reported_cost_usd": plan["failed_attempt_reported_cost_usd"], "historical_error_billing": plan["historical_error_billing"]}), flush=True)
            return
        if args.validate_only:
            plan = json.loads((ROOT / args.plan).read_text())
            validate_plan(plan, parent, cfg, launch, preflight)
            out = Path(os.environ["RESULTS_DIR"])
            imported = seed_child(parent, out, cfg, plan, os.environ["RUN_ID"])
            runner.verify_resume_artifacts(out, cfg, runner.identity(cfg), json.loads(launch.read_text()), preflight)
            (out / "recovery_validation.json").write_text(canonical({"evidence": "NOT_RESEARCH_DATA", "paid_calls": 0, "imports": len(imported), "all_pass": True, "source_evidence": "Parent inventory, frozen code/config/launch/preflight, call and unit journals, identical imported outcomes and recovery code archive validated."}))
            print(canonical({"status": "recovery_validation_pass", "imports": len(imported), "paid_calls": 0}), flush=True)
            return
        require(bool(args.awake_heartbeat), "Keep-awake heartbeat required")
        deadline = time.monotonic() + 90
        while True:
            try:
                heartbeat(args.awake_heartbeat)
                break
            except IntegrityError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.25)
        plan = json.loads((ROOT / args.plan).read_text())
        validate_plan(plan, parent, cfg, launch, preflight)
        out = Path(os.environ["RESULTS_DIR"])
        child_id = os.environ["RUN_ID"]
        seed_child(parent, out, cfg, plan, child_id)
    print(canonical({"status": "recovery_started", "run_id": child_id, "imported": plan["import_count"], "new_paid_units": 720-plan["import_count"], "retry_units": plan["retry_units"]}), flush=True)
    install_guards(args.awake_heartbeat, plan["failed_attempt_reported_cost_usd"])
    with (out / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner.execute(cfg, out, False, launch, preflight)
    verify_imports(out, parent, plan)
    cost = sum(r["reported_cost_usd"] for r in read_lines(out / "records.jsonl"))
    (out / "recovery_billing.json").write_text(canonical({"effective_outcome_reported_cost_usd": cost, "superseded_attempt_reported_cost_usd": plan["failed_attempt_reported_cost_usd"], "all_attempts_reported_cost_usd": cost + plan["failed_attempt_reported_cost_usd"], "historical_unverified_charge": plan["historical_error_billing"]}))


if __name__ == "__main__":
    main()
