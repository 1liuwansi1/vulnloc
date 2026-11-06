"""Validate recovery lineage then use the unchanged, frozen scientific analysis."""
import json
import sys
from pathlib import Path
import c06_recovery_v2 as recovery


def main():
    args = sys.argv
    raw = recovery.ROOT / args[args.index("--raw-dir") + 1]
    plan = json.loads((raw / "recovery_plan.json").read_text())
    parent = recovery.ROOT / "07_results/raw" / plan["parent_run_id"]
    cfg = json.loads((raw / "config.json").read_text())
    recovery.validate_plan(plan, parent, cfg, recovery.ROOT / plan["launch"], recovery.ROOT / plan["preflight"])
    recovery.verify_imports(raw, parent, plan)
    recovery.runner.verify_run_history(raw, {recovery.key(r) for r in recovery.read_lines(raw / "records.jsonl")})
    billing = json.loads((raw / "recovery_billing.json").read_text())
    expected = sum(r["reported_cost_usd"] for r in recovery.read_lines(raw / "records.jsonl"))
    recovery.require(billing["effective_outcome_reported_cost_usd"] == expected, "Recovery billing differs")
    recovery.require(billing["all_attempts_reported_cost_usd"] == expected + plan["failed_attempt_reported_cost_usd"], "Failed attempt cost omitted")
    import analysis
    analysis.main()
    processed = recovery.ROOT / args[args.index("--processed-dir") + 1]
    (processed / "recovery_provenance.json").write_text(recovery.canonical({"parent_run_id": parent.name, "imported_units": plan["import_count"], "explicit_retry_units": plan["retry_units"], "billing": billing, "note": "Imported outcomes are identical except child run_id and explicit lineage. Model-output failures were retained; the pre-request guard failure was retried once; prior attempt billing remains in the parent lineage. Frozen scoring unchanged."}))


if __name__ == "__main__":
    main()
