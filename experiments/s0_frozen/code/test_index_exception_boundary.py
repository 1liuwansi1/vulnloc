#!/usr/bin/env python3
"""Targeted index-boundary regression through real runner + real harness.

Only temporary indexes, a two-unit synthetic schedule and mock LLMs are used.
No formal indexes/raw predictions, embedding builds, or provider requests.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arms
import common as C
import rag_index as R
import runner
from mocks import FakeEmbedder, MockLLM

ROOT = Path(C.ROOT)
REPORT = ROOT / "06_experiments/c06/index_exception_boundary_test.json"


def fixture(root, scenario):
    """Child process: real runner main with entirely isolated acquisition inputs."""
    row = dict(entry_id="synthetic", report_id="synthetic", project="synthetic",
               repo_url="https://synthetic/repo", commit="a" * 40, stratum="synthetic",
               vuln_category_l2="synthetic", vuln_title="synthetic", task_description="synthetic",
               ep_file="x.py", co_file="y.py", ep_line="1", co_line="1", role="confirmatory")
    index = root / "index"
    index.mkdir()
    chunks = [{"path": "x.py", "start": 1, "end": 1, "text": "fixture text"}]
    cb = json.dumps(chunks).encode()
    emb = np.ones((1, 384), dtype=np.float32)
    meta = dict(project=row["project"], repo_url=row["repo_url"], commit=row["commit"],
                index_config_hash="synthetic", embedding_config_hash=R.embedding_config_hash(),
                chunks_sha256=hashlib.sha256(cb).hexdigest(),
                emb_sha256=hashlib.sha256(emb.tobytes()).hexdigest(), num_chunks=1, dim=384)
    if scenario != "missing":
        (index / "chunks.json").write_bytes(cb)
        (index / "index_meta.json").write_text(json.dumps(meta))
        if scenario == "npz_at_npy":
            with (index / "emb.npy").open("wb") as f:
                np.savez(f, emb=emb)
        elif scenario == "corrupt_npy":
            (index / "emb.npy").write_bytes(b"not a numpy file")
        else:
            np.save(index / "emb.npy", emb)
    mf = root / "06_experiments/c06"
    mf.mkdir(parents=True)
    (mf / "confirmatory_index_manifest.json").write_text(json.dumps(
        {"indexes": [dict(meta, emb_row_count=1)]}))
    repo = root / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("fixture text\n")
    trace = {"index_calls": 0, "pack_calls": 0, "llm_calls": 0}
    original_get, original_pack = arms._get_index, arms.run_arm_pack

    def get(*args):
        trace["index_calls"] += 1
        return original_get(*args)

    def pack(*args):
        trace["pack_calls"] += 1
        return original_pack(*args)

    def build(arm, mock, event_log=None):
        llm = MockLLM(C.TASK_HEADER)
        original_prompt = llm.prompt

        def prompt(text):
            trace["llm_calls"] += 1
            if scenario == "provider_error" and arm == "rag":
                return dict(text="", input=0, output=0, reasoning=0, cost=0,
                            provider_error=True, error="synthetic provider error",
                            saw_message_end=True)
            return original_prompt(text)
        llm.prompt = prompt
        return llm

    with patch.object(C, "ROOT", str(root)), \
            patch.object(C, "load_manifest", return_value=[row]), \
            patch.object(C, "repo_dir", return_value=str(repo)), \
            patch.object(R, "_index_dir", return_value=str(index)), \
            patch.object(runner, "RETRY_BACKOFF_S", 0), \
            patch.object(runner, "FakeEmbedder", return_value=FakeEmbedder(dim=384)), \
            patch.object(runner, "load_schedule", return_value={"synthetic": [(1, 1, "rag"), (1, 2, "pack")]}), \
            patch.object(runner, "build_llm", side_effect=build), \
            patch.object(arms, "_get_index", side_effect=get), \
            patch.object(arms, "run_arm_pack", side_effect=pack), \
            patch.object(sys, "argv", ["runner", "--phase", "confirmatory", "--mock"]):
        if scenario == "loader_attribute_error":
            with patch.object(R, "load_index_integrity", side_effect=AttributeError("synthetic loader attribute")):
                code = runner.main()
        else:
            code = runner.main()
    Path(os.environ["RESULTS_DIR"], "fixture_trace.json").write_text(json.dumps(trace))
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture")
    ap.add_argument("--scenario")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()
    if args.fixture:
        return fixture(Path(args.fixture), args.scenario)
    results = []
    with tempfile.TemporaryDirectory(prefix="c06-index-boundary-") as tmp:
        for scenario in ("npz_at_npy", "corrupt_npy", "loader_attribute_error", "missing", "valid", "provider_error"):
            root = Path(tmp) / scenario
            root.mkdir()
            # Real harness uses an isolated ROOT; no repository metadata/log/raw writes.
            launch = root / "harness_fixture.py"
            launch.write_text(
                "import importlib.util,sys\n"
                f"s=importlib.util.spec_from_file_location('h', {str(ROOT / 'scripts/run_experiment.py')!r})\n"
                "h=importlib.util.module_from_spec(s);s.loader.exec_module(h)\n"
                f"h.ROOT={str(root)!r}\n"
                "h.main()\n")
            command = [sys.executable, "-B", str(Path(__file__).resolve()),
                       "--fixture", str(root), "--scenario", scenario]
            cfg = root / "config.yaml"
            cfg.write_text(yaml.safe_dump(dict(name="c06-confirmatory", seed=20260928,
                                               command=command, timeout=60)))
            p = subprocess.run([sys.executable, "-B", str(launch), "--config", str(cfg),
                                "--allow-no-git", "--quiet"], capture_output=True, text=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=90)
            metas = list((root / "06_experiments/metadata").glob("*.yaml"))
            assert len(metas) == 1, p.stderr
            meta = yaml.safe_load(metas[0].read_text())
            raw = root / meta["paths"]["raw"]
            records = [json.loads(s) for s in (raw / "records.jsonl").read_text().splitlines()]
            trace = json.loads((raw / "fixture_trace.json").read_text())
            summary = json.loads((raw / "summary.json").read_text())
            if scenario in ("valid", "provider_error"):
                ok = (p.returncode == 0 and meta["status"] == "success"
                      and trace["pack_calls"] == 1 and len(records) == 2
                      and summary["guard_state"] == "ok")
                if scenario == "valid":
                    ok = ok and trace["index_calls"] == 1 and all(r["failure_category"] is None for r in records)
                else:
                    ok = ok and trace["index_calls"] == 3 and records[0]["failure_category"] == "api_error" and records[0]["attempts"] == 3
            else:
                ok = (p.returncode == runner.INDEX_INFRA_EXIT and meta["exit_code"] == runner.INDEX_INFRA_EXIT
                      and meta["status"] == "infrastructure_error" and len(records) == 1
                      and records[0]["failure_category"] == "infrastructure_error"
                      and records[0]["attempts"] == 1 and trace == dict(index_calls=1, pack_calls=0, llm_calls=0)
                      and summary["guard_state"] == "infrastructure_error")
            results.append(dict(name=scenario, passed=bool(ok), runner_exit=meta["exit_code"],
                                harness_exit=p.returncode, metadata_status=meta["status"],
                                trace=trace, failures=[r["failure_category"] for r in records],
                                attempts=[r["attempts"] for r in records]))
            print(f"{scenario}: {'PASS' if ok else 'FAIL'}")
    report = dict(all_pass=all(r["passed"] for r in results), tests=results,
                  indexes_rebuilt=0, experimental_llm_calls=0)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
