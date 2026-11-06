#!/usr/bin/env python3
"""B1/B2 regressions: real frozen manifest + real producer -> full synthetic CLI.

No experiment LLM, real predictions, index writes, or 720-run runner execution.
Only analysis runs, on 720 fabricated valid empty answers in temporary directories.
The committed report contains test outcomes, never synthetic performance numbers.
"""
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import runner

RUN_ID = "c06-confirmatory-synthetic-b1-b2"
ATTEMPT1 = "c06-confirmatory-20260929T114451Z-bb50"
REPORT = os.path.join(C.C06_DIR, "entrypoint_integration_test.json")


def synthetic_records():
    with open(C.CONFIRMATORY_MANIFEST, encoding="utf-8") as f:
        sample = {r["entry_id"]: r for r in csv.DictReader(f) if r["role"] == "confirmatory"}
    with open(C.CONFIRMATORY_SCHEDULE, encoding="utf-8") as f:
        records = []
        for s in csv.DictReader(f):
            row = sample[s["entry_id"]]
            records.append({"entry_id": s["entry_id"], "arm": s["arm"], "repeat": int(s["repeat"]),
                            "answer": None, "failure_category": "empty_answer", "experiment_run_id": RUN_ID,
                            "provider": "deepseek", "model": "deepseek-v4-pro", "thinking": "high", "mock": False,
                            "seed": 0, "prompt_config_hash": runner.config_hash(s["arm"], row),
                            **{k: row[k] for k in ("report_id", "project", "repo_url", "commit", "stratum", "vuln_category_l2")},
                            "cost_usd": 0.0, "wall_seconds": 0.0})
        return records


def main():
    results = []

    def check(name, ok, detail=""):
        results.append({"name": name, "pass": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    records = synthetic_records()
    assert len(records) == 720
    # Use the actual launch manifest, never manufacture a test-only replacement.
    with open(C.LAUNCH_MANIFEST, encoding="utf-8") as f:
        launch = json.load(f)
    with open(os.path.join(C.ROOT, C.FROZEN_FILES["experiment_config"]), encoding="utf-8") as f:
        config = yaml.safe_load(f)
    runtime = subprocess.check_output(["git", "-C", C.ROOT, "rev-parse", "HEAD"], text=True).strip()
    metadata = {"status": "success", "run_id": RUN_ID, "git": {"commit": runtime},
                "config": config, "command": config["command"], "seed": config["seed"]}

    with tempfile.TemporaryDirectory(prefix="c06-b1-b2-") as tmp:
        raw = Path(tmp) / "raw"
        raw.mkdir()
        # THIS is the production function. All provenance fields come from it.
        identity = runner.write_freeze_identity(str(raw))
        check("B1 real producer uses actual frozen manifest", identity["implementation_commit"] == launch["implementation_commit"])
        bindings = {"config_sha256": "experiment_config", "sample_manifest_sha256": "sample_manifest",
                    "schedule_sha256": "run_schedule", "index_manifest_sha256": "index_manifest",
                    "evaluator_sha256": "evaluator"}
        check("B1 actual producer hashes match launch", all(identity[k] == launch["frozen_file_sha256"][v]
                                                          for k, v in bindings.items()))
        # Force CRLF independently of checkout settings, without editing any real input.
        crlf_sample = Path(tmp) / "sample-crlf.csv"
        source = Path(C.CONFIRMATORY_MANIFEST).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        crlf_sample.write_bytes(source.replace(b"\n", b"\r\n"))
        with patch.dict(C.FROZEN_FILES, {"sample_manifest": str(crlf_sample)}):
            crlf_identity = runner.write_freeze_identity(str(Path(tmp) / "crlf-producer"))
        check("B1 forced CRLF is normalized by real producer",
              crlf_identity["sample_manifest_sha256"] == launch["frozen_file_sha256"]["sample_manifest"]
              and hashlib.sha256(crlf_sample.read_bytes()).hexdigest() != crlf_identity["sample_manifest_sha256"])

        def run_case(name, *, fi=identity, meta=metadata, rs=records, run_id=RUN_ID,
                     fi_text=None, meta_text=None, missing=None, success=False, error_contains=None):
            case = Path(tmp) / f"case-{len(results):03d}"
            case.mkdir()
            case_raw = case / "raw"
            case_raw.mkdir()
            (case_raw / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rs), encoding="utf-8")
            if missing != "identity":
                (case_raw / "freeze_identity.json").write_text(fi_text if fi_text is not None else json.dumps(fi), encoding="utf-8")
            meta_path = case / "meta.yaml"
            if missing != "metadata":
                meta_path.write_text(meta_text if meta_text is not None else yaml.safe_dump(meta), encoding="utf-8")
            processed, tables = case / "processed", case / "tables"
            cmd = [sys.executable, "-B", os.path.join(C.C06_DIR, "..", "scripts", "c06", "analyze_c06_confirmatory.py"),
                   "--run-id", run_id, "--metadata", str(meta_path), "--raw-dir", str(case_raw),
                   "--processed-dir", str(processed), "--tables-dir", str(tables), "--figures-dir", str(case / "figures")]
            env = dict(os.environ, C06_LAUNCH_MANIFEST=C.LAUNCH_MANIFEST, PYTHONDONTWRITEBYTECODE="1")
            p = subprocess.run(cmd, cwd=C.ROOT, env=env, capture_output=True, text=True, timeout=180)
            if success:
                ok = p.returncode == 0 and (processed / "stats.json").is_file() and (tables / "summary.md").is_file()
                if ok:
                    stats = json.loads((processed / "stats.json").read_text())["stats"]
                    ok = stats["primary"]["agent_vs_pack"]["n"] == 80 and set(stats["secondary"]["bh_family_members"]) == {
                        "fr_agent_vs_rag", "fr_rag_vs_pack", "lr_agent_vs_rag", "lr_rag_vs_pack"}
            else:
                ok = p.returncode != 0 and "[analyze_confirmatory] FAIL:" in p.stdout and not processed.exists() and not tables.exists()
                if error_contains is not None:
                    ok = ok and error_contains in p.stdout
            check(name, ok, f"exit={p.returncode}")
            if not ok:
                # Gate diagnostics only; never print result summaries.
                print("\n".join(line for line in (p.stdout + p.stderr).splitlines()
                                if "FAIL" in line or line.startswith("  - ")))

        run_case("B1 real producer -> full synthetic 720 CLI", success=True)
        run_case("B1 forced CRLF producer -> full synthetic 720 CLI", fi=crlf_identity, success=True)
        for label, value in (("empty object", {}), ("null", None), ("array", []), ("string", "x"), ("number", 0), ("boolean", False)):
            run_case("B2 identity " + label, fi=value)
        run_case("B2 malformed identity JSON", fi_text="{truncated")
        run_case("B2 missing identity file", missing="identity")
        run_case("B2 empty identity plus missing metadata commit", fi={}, meta=dict(metadata, git={}))

        for field in identity:
            for kind, value in (("missing", None), ("null", None), ("empty", ""), ("wrong type", []), ("malformed", "not-a-valid-value")):
                changed = dict(identity)
                if kind == "missing":
                    del changed[field]
                else:
                    changed[field] = value
                run_case(f"B2 identity {field}: {kind}", fi=changed)
        for field in ("actual_runtime_git_commit", "implementation_commit", "launch_manifest_sha256", *bindings):
            changed = dict(identity, **{field: "0" * (40 if "commit" in field else 64)})
            run_case(f"identity mismatch {field}", fi=changed)
        run_case("runtime and metadata agree on invalid commit", fi=dict(identity, actual_runtime_git_commit="0" * 40),
                 meta=dict(metadata, git={"commit": "0" * 40}))

        for label, value in (("empty object", {}), ("null", None), ("array", []), ("string", "x")):
            run_case("B2 metadata " + label, meta=value)
        run_case("B2 malformed metadata YAML", meta_text="git: [")
        run_case("B2 missing metadata file", missing="metadata")
        paths = [(k,) for k in ("status", "run_id", "git", "config", "command", "seed")]
        paths += [("git", "commit")]
        paths += [("config", k) for k in config]
        paths += [("config", "env", k) for k in config["env"]]
        for path in paths:
            for kind, value in (("missing", None), ("null", None), ("malformed", [])):
                changed = copy.deepcopy(metadata)
                obj = changed
                for key in path[:-1]:
                    obj = obj[key]
                if kind == "missing":
                    del obj[path[-1]]
                else:
                    obj[path[-1]] = value
                run_case(f"B2 metadata {'.'.join(path)}: {kind}", meta=changed)
        run_case("wrong metadata run_id", meta=dict(metadata, run_id="c06-confirmatory-other"))
        run_case("aborted metadata status", meta=dict(metadata, status="aborted_infra"))
        run_case("fake run_id without metadata", run_id="c06-confirmatory-fake", missing="metadata")
        run_case("Attempt 1 exclusion", run_id=ATTEMPT1)
        mixed = copy.deepcopy(records)
        mixed[0]["experiment_run_id"] = "other"
        run_case("mixed record run_id", rs=mixed)
        run_case("719 units", rs=records[:-1])
        run_case("duplicate replacing unit at 720", rs=records[:-1] + [records[0]])
        run_case("extra duplicate at 721", rs=records + [records[0]])
        for category in ("infrastructure_error", "api_error", "runner_error", "timeout", "unknown_failure"):
            bad = copy.deepcopy(records)
            bad[0]["failure_category"] = category
            run_case("infra gate: " + category, rs=bad)

        # Keep the prior 151 cases intact; all new unit-level regressions follow.
        assert len(results) == 151
        from test_provider_failures import produce_record, SCENARIOS
        with open(C.CONFIRMATORY_MANIFEST, encoding="utf-8") as f:
            sample = {r["entry_id"]: r for r in csv.DictReader(f) if r["role"] == "confirmatory"}
        for arm in ("agent", "rag", "pack"):
            idx = next(i for i, r in enumerate(records) if r["arm"] == arm)
            row = dict(sample[records[idx]["entry_id"]], _rep=records[idx]["repeat"])
            for scenario in SCENARIOS:
                rec = produce_record(scenario, arm, row, os.path.join(tmp, "rpc", arm, scenario), RUN_ID)
                assert rec["failure_category"] == "api_error" and rec["attempts"] == 3
                bad = copy.deepcopy(records)
                bad[idx] = rec  # Untouched output from the real client/arm/retry path.
                run_case(f"B1 real RPC -> {arm} -> retries -> 720 gate: {scenario}", rs=bad,
                         error_contains="infra/transport failure api_error")

        for field, value in (("model", "wrong-model"), ("provider", "wrong-provider"), ("thinking", "low"),
                             ("mock", True), ("commit", "0" * 40), ("report_id", "other-report"),
                             ("project", "other-project"), ("repo_url", "https://other/repo"),
                             ("stratum", "other-stratum"), ("vuln_category_l2", "other-category"),
                             ("prompt_config_hash", "0" * 16), ("seed", 1)):
            bad = copy.deepcopy(records)
            bad[0][field] = value
            run_case("B2 one-unit provenance mismatch: " + field, rs=bad)

        required = ("entry_id", "arm", "repeat", "experiment_run_id", "provider", "model", "thinking", "mock",
                    "report_id", "project", "repo_url", "commit", "stratum", "vuln_category_l2", "seed",
                    "prompt_config_hash", "answer", "failure_category")
        for field in required:
            for kind, value in (("missing", None), ("null", None), ("wrong type", [])):
                # answer=null is the real serialized representation of a model
                # failure; test its illegality with success instead (below).
                if kind == "null" and field == "answer":
                    continue
                bad = copy.deepcopy(records)
                if kind == "missing":
                    del bad[0][field]
                else:
                    bad[0][field] = value
                run_case(f"B3 required record {field}: {kind}", rs=bad)
        for field, value in (("repeat", 1.9), ("repeat", "1"), ("repeat", True), ("repeat", 0), ("repeat", 4),
                             ("arm", "invalid-arm"), ("entry_id", "outside-schedule"), ("entry_id", ""),
                             ("mock", 0), ("mock", "false"), ("seed", False), ("failure_category", "unknown")):
            bad = copy.deepcopy(records)
            bad[0][field] = value
            run_case(f"B3 exact unit/schema {field}={value!r}", rs=bad)
        for value in (None, {}, {"candidate_files": None}, {"candidate_files": [None]},
                      {"candidate_files": [{"path": 1}]}, {"candidate_files": []}):
            bad = copy.deepcopy(records)
            bad[0]["failure_category"] = None
            bad[0]["answer"] = value
            run_case("B3 successful-answer schema " + repr(value), rs=bad,
                     success=value == {"candidate_files": []})
        for value in ({}, [], None, "not a record"):
            bad = copy.deepcopy(records)
            bad[0] = value
            run_case("B3 invalid record object " + repr(value), rs=bad)

    allpass = all(r["pass"] for r in results)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump({"all_pass": allpass, "prior_151_pass": all(r["pass"] for r in results[:151]),
                   "tests": results}, f, indent=2, ensure_ascii=False)
    print(f"PRODUCER/CONSUMER INTEGRATION: {'PASS' if allpass else 'FAIL'} ({len(results)} checks)")
    return 0 if allpass else 1


if __name__ == "__main__":
    sys.exit(main())
