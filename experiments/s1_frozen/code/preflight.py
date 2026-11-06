"""Executable prelaunch evidence gate. No score-based filtering or paid retries."""


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


import argparse
import json
import math
from pathlib import Path
import yaml
from core import ROOT, IntegrityError, digest_file, canonical, fingerprint, read_config
from runner import identity
from billing import inspect_journal
from runner import schedule, load_rows


def verify_pilot_identity(actual, expected_cfg):
    expected = identity(expected_cfg)
    if (
        actual["config"] != expected["config"]
        or actual["manifest_sha256"] != expected["manifest_sha256"]
    ):
        raise IntegrityError(
            "Pilot config or manifest differs from predetermined development matrix"
        )
    excluded = {"preflight.py", "analysis.py"}
    for name, value in expected["code"].items():
        if Path(name).name in excluded or Path(name).name.startswith("test_"):
            continue
        if actual["code"].get(name) != value:
            raise IntegrityError("Pilot native execution component changed: " + name)


def check_artifact(report):
    for name, expected in report["evidence_sha256"].items():
        if digest_file(ROOT / name) != expected:
            raise IntegrityError("Preflight evidence changed: " + name)


def validate(report, cfg, launch):
    if report["verdict"] != "PASS" or report["identity"] != identity(cfg):
        raise IntegrityError("Preflight missing/failed/stale")
    if report["launch_sha256"] != digest_file(launch):
        raise IntegrityError("Preflight launch changed")
    check_artifact(report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launch", required=True)
    parser.add_argument("--pilot-run", required=True)
    parser.add_argument("--arms-run", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    folder = ROOT / "06_experiments/c06_repair"
    cfg = read_config(folder / "formal_proposal.json")
    launch = ROOT / args.launch
    contract = json.loads(launch.read_text())
    require(
        contract["identity"] == identity(cfg) and (not contract["mock"]),
        "Preflight check failed: contract['identity'] == identity(cfg) and (not contract['mock'])",
    )
    require(
        len(contract["repos"]) == 74 and len(contract["schedule"]) == 720,
        "Preflight check failed: len(contract['repos']) == 74 and len(contract['schedule']) == 720",
    )
    require(
        fingerprint(contract) == launch.stem,
        "Preflight check failed: fingerprint(contract) == launch.stem",
    )
    evidence = [launch]
    for name in ("transport_tests.json", "integration_tests.json", "repair_audit.json"):
        path = folder / name
        report = json.loads(path.read_text())
        require(report["all_pass"], "Preflight check failed: report['all_pass']")
        require("code" in report, "Audit report lacks version identity: " + name)
        require(
            report["code"] == identity(cfg)["code"],
            "Preflight check failed: report['code'] == identity(cfg)['code']",
        )
        evidence.append(path)
    review = json.loads((folder / "independent_review_resolution.json").read_text())
    require(
        review["blocking_unresolved"] == 0,
        "Preflight check failed: review['blocking_unresolved'] == 0",
    )
    require(
        review["code"] == identity(cfg)["code"],
        "Preflight check failed: review['code'] == identity(cfg)['code']",
    )
    evidence += [
        folder / "independent_review_resolution.json",
        folder / "independent_review.md",
    ]
    for name, count in (
        ("local_tests.log", 28),
        ("repair_tests.log", 14),
        ("native_tests.log", 10),
    ):
        path = folder / name
        log = path.read_text()
        require(
            f"Ran {count} tests" in log and log.strip().endswith("OK"),
            "Preflight check failed: f'Ran {count} tests' in log and log.strip().endswith('OK')",
        )
        evidence.append(path)
    pilot = ROOT / "07_results/raw" / args.pilot_run
    meta = ROOT / "06_experiments/metadata" / (args.pilot_run + ".yaml")
    require(
        yaml.safe_load(meta.read_text())["status"] == "success",
        "Preflight check failed: yaml.safe_load(meta.read_text())['status'] == 'success'",
    )
    pilot_identity = json.loads((pilot / "identity.json").read_text())
    pilot_cfg = read_config(folder / "development_multirepo.json")
    verify_pilot_identity(pilot_identity, pilot_cfg)
    require(
        all(
            (
                pilot_cfg[key] == cfg[key]
                for key in (
                    "provider",
                    "model",
                    "thinking",
                    "budget_a",
                    "chunk_lines",
                    "chunk_overlap",
                    "max_tool_calls",
                    "max_turns",
                    "turn_timeout",
                    "wire_protocol",
                    "timeout_clock",
                    "agent_interface",
                )
            )
        ),
        "Preflight check failed: all((pilot_cfg[key] == cfg[key] for key in ('provider', 'model', 'thinking', 'budget_a', 'chunk_lines', 'chunk_overlap', 'max_tool_calls', 'max_turns', 'turn_timeout', 'wire_protocol', 'timeout_clock', 'agent_interface')))",
    )
    records = list(map(json.loads, (pilot / "records.jsonl").read_text().splitlines()))
    require(
        len(records) == 6 and len({r["entry_id"] for r in records}) == 3,
        "Preflight check failed: len(records) == 6 and len({r['entry_id'] for r in records}) == 3",
    )
    require(
        len({(r["entry_id"], r["repeat"]) for r in records}) == 6,
        "Preflight check failed: len({(r['entry_id'], r['repeat']) for r in records}) == 6",
    )
    require(
        {(r["entry_id"], r["arm"], r["repeat"]) for r in records}
        == {
            (r["entry_id"], r["arm"], r["repeat"])
            for r in schedule(load_rows(pilot_cfg), pilot_cfg)
        },
        "Preflight check failed: {(r['entry_id'], r['arm'], r['repeat']) for r in records} == {(r['entry_id'], r['arm'], r['repeat']) for r in schedule(load_rows(pilot_cfg), pilot_cfg)}",
    )
    require(
        all(
            (
                not r["mock"]
                and r["arm"] == "agent"
                and (r["failure_category"] is None)
                for r in records
            )
        ),
        "Preflight check failed: all((not r['mock'] and r['arm'] == 'agent' and (r['failure_category'] is None) for r in records))",
    )
    require(
        all((r["trajectory"] for r in records)),
        "Preflight check failed: all((r['trajectory'] for r in records))",
    )
    require(
        all((r["A"] <= 50000 for r in records)),
        "Preflight check failed: all((r['A'] <= 50000 for r in records))",
    )
    journal = inspect_journal(pilot / "call_journal.jsonl")
    require(not journal["pending"], "Preflight check failed: not journal['pending']")
    require(
        math.isclose(
            journal["known_cost_usd"],
            sum((r["reported_cost_usd"] for r in records)),
            abs_tol=1e-09,
        ),
        "Preflight check failed: math.isclose(journal['known_cost_usd'], sum((r['reported_cost_usd'] for r in records)), abs_tol=1e-09)",
    )
    evidence += [
        meta,
        pilot / "identity.json",
        pilot / "records.jsonl",
        pilot / "call_journal.jsonl",
    ]
    arms = ROOT / "07_results/raw" / args.arms_run
    arms_meta = ROOT / "06_experiments/metadata" / (args.arms_run + ".yaml")
    require(
        yaml.safe_load(arms_meta.read_text())["status"] == "success",
        "Preflight check failed: yaml.safe_load(arms_meta.read_text())['status'] == 'success'",
    )
    arms_cfg = read_config(folder / "development.json")
    verify_pilot_identity(json.loads((arms / "identity.json").read_text()), arms_cfg)
    arms_records = list(
        map(json.loads, (arms / "records.jsonl").read_text().splitlines())
    )
    require(
        len(arms_records) == 3
        and {r["arm"] for r in arms_records} == {"agent", "rag", "pack"},
        "Preflight check failed: len(arms_records) == 3 and {r['arm'] for r in arms_records} == {'agent', 'rag', 'pack'}",
    )
    require(
        all((not r["mock"] and r["failure_category"] is None for r in arms_records)),
        "Preflight check failed: all((not r['mock'] and r['failure_category'] is None for r in arms_records))",
    )
    arms_bill = inspect_journal(arms / "call_journal.jsonl")
    require(
        not arms_bill["pending"]
        and math.isclose(
            arms_bill["known_cost_usd"],
            sum((r["reported_cost_usd"] for r in arms_records)),
            abs_tol=1e-09,
        ),
        "Preflight check failed: not arms_bill['pending'] and math.isclose(arms_bill['known_cost_usd'], sum((r['reported_cost_usd'] for r in arms_records)), abs_tol=1e-09)",
    )
    evidence += [
        arms_meta,
        arms / "identity.json",
        arms / "records.jsonl",
        arms / "call_journal.jsonl",
    ]
    historical = inspect_journal(
        ROOT
        / "07_results/raw/c06-revision-formal-20261003T144840Z-7e5d/call_journal.jsonl"
    )
    result = {
        "verdict": "PASS",
        "scope": "New fresh repair-version run only; no automatic reuse/resume of interrupted parent",
        "identity": identity(cfg),
        "launch_sha256": digest_file(launch),
        "evidence_sha256": {
            str(path.relative_to(ROOT)): digest_file(path) for path in evidence
        },
        "native_pilot_run": args.pilot_run,
        "native_pilot_units": 6,
        "three_arm_development_run": args.arms_run,
        "pilot_version_policy": "Exact config, manifest, and native execution kernels; separate preflight/test/analysis modules are independently checked at their final version",
        "historical_billing": historical,
        "limitations": [
            "Prior interrupted request remains UNKNOWN; do not infer zero billing",
            "Format adapter was developed using observed prior failures; new study is supplemental",
            "No guarantee of effect size, acceptance or all future errors",
            "No automatic paid retries or analysis of incomplete research",
            "Keep the host and WSL running; monotonic timing cannot repair network loss during suspend",
        ],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(canonical(result))
    print(
        canonical(
            {
                "verdict": result["verdict"],
                "scope": result["scope"],
                "pilot_units": 6,
                "historical_unknown_calls": len(historical["pending"]),
            }
        )
    )


if __name__ == "__main__":
    main()
