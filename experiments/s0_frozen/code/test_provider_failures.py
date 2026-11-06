#!/usr/bin/env python3
"""Synthetic provider failures through REAL PiRpcLLM -> arm -> runner retries.

Only the executable is replaced with fake_pi.py; prompt/arm/retry code is real.
No provider calls, experimental results, or frozen index modifications.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import arms
import common as C
import runner
from mocks import FakeEmbedder
from pi_rpc import PiRpcLLM

SCENARIOS = ("provider_503", "stop_error", "error_message", "retry_failed", "rpc_failed",
             "stream_error", "aborted", "provider_event")
FAKE = str(Path(__file__).with_name("fake_pi.py"))


def produce_record(scenario, arm, row, output_dir, run_id):
    """The returned record is untouched runner output (including attempts/events)."""
    def local_rpc(system, **kwargs):
        return PiRpcLLM(system, pi_bin=[sys.executable, "-B", FAKE, scenario], turn_timeout=5, **kwargs)

    env = {"C06_PROVIDER": "deepseek", "C06_MODEL": "deepseek-v4-pro", "C06_THINKING": "high", "RUN_ID": run_id}
    # Tiny local repository/index fixture only; all three arms and real retries execute.
    with tempfile.TemporaryDirectory(prefix="c06-provider-repo-") as repo, \
            patch.dict(os.environ, env), patch.object(runner, "PiRpcLLM", side_effect=local_rpc), \
            patch.object(runner.C, "repo_dir", return_value=repo), patch.object(runner, "RETRY_BACKOFF_S", 0), \
            patch.object(arms, "_get_index", return_value=([
                {"path": "synthetic.py", "start": 1, "end": 1, "text": "synthetic fixture"}],
                np.ones((1, 384), dtype="float32"))):
        return runner.run_one_with_retry(arm, row, output_dir, mock=False, embedder=FakeEmbedder(dim=384))


def main():
    row = {"entry_id": "synthetic", "report_id": "synthetic", "project": "synthetic", "repo_url": "https://synthetic/repo",
           "commit": "a" * 40, "stratum": "synthetic", "vuln_category_l2": "synthetic", "vuln_title": "synthetic",
           "task_description": "synthetic", "_rep": 1}
    results = []
    with tempfile.TemporaryDirectory(prefix="c06-provider-errors-") as tmp:
        for arm in ("agent", "rag", "pack"):
            for scenario in SCENARIOS:
                output = os.path.join(tmp, arm, scenario)
                rec = produce_record(scenario, arm, row, output, "c06-confirmatory-synthetic-provider")
                events = [a["events_file"] for a in rec["attempts_info"]]
                ok = (rec["failure_category"] == "api_error" and rec["answer"] is None and rec["attempts"] == 3
                      and all(a["failure_category"] == "api_error" for a in rec["attempts_info"])
                      and len(set(events)) == 3 and all(os.path.isfile(os.path.join(output, e)) for e in events)
                      and rec["cost_usd_total_attempts"] == round(sum(a["cost_usd"] for a in rec["attempts_info"]), 6))
                if scenario == "provider_503":
                    ok = ok and "503" in rec["error"] and rec["cost_usd_total_attempts"] == 0.003
                results.append({"name": f"{arm}/{scenario}: infra + three attempts + preserved evidence", "pass": bool(ok)})
            rec = produce_record("complete_empty", arm, row, os.path.join(tmp, arm, "complete_empty"), "c06-confirmatory-synthetic-provider")
            results.append({"name": f"{arm}/legitimate empty: scientific outcome, no infra retry",
                            "pass": rec["failure_category"] in ("empty_answer", "invalid_json") and rec["attempts"] == 1})
    all_pass = all(r["pass"] for r in results)
    for r in results:
        print(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['name']}")
    with open(os.path.join(C.C06_DIR, "provider_failure_test.json"), "w", encoding="utf-8") as f:
        json.dump({"all_pass": all_pass, "tests": results}, f, indent=2)
    print(f"PROVIDER FAILURE REGRESSIONS: {'PASS' if all_pass else 'FAIL'} ({len(results)})")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
