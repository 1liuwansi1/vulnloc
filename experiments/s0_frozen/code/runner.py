#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner.py — C-06 micro-MVE 编排（Pi RPC DeepSeek V4 Pro High 固定模型；调度冻结；infra 重试）。"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms
import rag_index
from mocks import FakeEmbedder, MockLLM
from pi_rpc import PiRpcLLM

SCHEDULE = os.path.join(C.ROOT, "06_experiments", "c06", "run_schedule.csv")
CONFIRMATORY_MANIFEST = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_sample_manifest.csv")
CONFIRMATORY_SCHEDULE = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_run_schedule.csv")
INFRA_FAILURES = {"api_error", "runner_error", "timeout"}
INFRA_RETRIES = 2
RETRY_BACKOFF_S = 10
INDEX_INFRA_EXIT = 86  # C-06 harness metadata: experiment-level index failure
# D-013 Phase 1.2：冻结模型锁（config 显式指定，FAIL CLOSED，禁止 PI_* 环境变量覆盖）
FROZEN_MODEL = {"provider": "deepseek", "model": "deepseek-v4-pro", "thinking": "high"}
MODEL_ENV = {"provider": "C06_PROVIDER", "model": "C06_MODEL", "thinking": "C06_THINKING"}


def load_schedule(path=SCHEDULE):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    sched = {}
    for r in rows:
        sched.setdefault(r["entry_id"], []).append((int(r["repeat"]), int(r["position"]), r["arm"]))
    for e in sched:
        sched[e].sort(key=lambda t: (t[0], t[1]))
    return sched


def build_llm(arm, mock, event_log=None):
    system = C.TASK_HEADER + ("\n\n" + arms.TOOL_DESC if arm == "agent" else "")
    if mock:
        return MockLLM(system)
    # FAIL CLOSED：只读 config 注入的 C06_* 环境，禁止 PI_* 覆盖；不匹配即抛异常停止
    got = {k: os.environ.get(v) for k, v in MODEL_ENV.items()}
    if got != FROZEN_MODEL:
        raise RuntimeError(f"[model-lock] FAIL CLOSED: frozen={FROZEN_MODEL} got={got}")
    return PiRpcLLM(system, provider=got["provider"], model=got["model"],
                    thinking=got["thinking"], event_log=event_log)


def config_hash(arm, row):
    system = C.TASK_HEADER + ("\n\n" + arms.TOOL_DESC if arm == "agent" else "")
    payload = "|".join([arm, system, C.task_user_text(row), json.dumps({"budget": C.BUDGET_A})])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def run_one(arm, row, results_dir, mock, embedder, attempt=0):
    repo = C.repo_dir(row["project"], row["commit"])
    ledger = C.Ledger()
    ev_dir = os.path.join(results_dir, "events")
    os.makedirs(ev_dir, exist_ok=True)
    ev_path = os.path.join(ev_dir, f"{row['entry_id']}__{arm}__rep{row.get('_rep', '')}__a{attempt}.jsonl")
    t0 = time.time()
    llm = None
    try:
        with open(ev_path, "w", encoding="utf-8") as evf:
            llm = build_llm(arm, mock, event_log=evf)
            if arm == "agent":
                res = arms.run_arm_agent(llm, row, repo, ledger)
            elif arm == "rag":
                res = arms.run_arm_rag(llm, row, repo, ledger, embedder)
            else:
                res = arms.run_arm_pack(llm, row, repo, ledger)
    except rag_index.IndexIntegrityError as ex:
        # fail-closed：index 完整性失败 → infrastructure_error（不 retry，整个实验停止）
        res = {"answer": None, "raw_text": "", "failure_category": "infrastructure_error",
               "accounting": {"A": 0, "A_unique": 0, "B": 0, "C": 0, "R": 0, "CR": 0, "D": 0, "F": 0, "cost": 0.0},
               "cost_usd": 0.0, "error": str(ex)[:400]}
    except Exception as ex:  # noqa: BLE001
        res = {"answer": None, "raw_text": "", "failure_category": "runner_error",
               "accounting": {"A": 0, "A_unique": 0, "B": 0, "C": 0, "R": 0, "CR": 0, "D": 0, "F": 0, "cost": 0.0},
               "cost_usd": 0.0, "error": str(ex)[:400]}
    finally:
        if llm is not None:
            llm.close()
    rec = {"entry_id": row["entry_id"], "report_id": row["report_id"], "project": row["project"],
           "repo_url": row["repo_url"], "commit": row["commit"], "stratum": row["stratum"],
           "vuln_category_l2": row["vuln_category_l2"], "arm": arm, "repeat": row.get("_rep"),
           "mock": mock, "provider": getattr(llm, "provider", "?"),
           "model": getattr(llm, "model", "?"), "thinking": getattr(llm, "thinking", "?"),
           "seed": 0, "wall_seconds": round(time.time() - t0, 3),
           "experiment_run_id": os.environ.get("RUN_ID"),
           "prompt_config_hash": config_hash(arm, row),
           "events_file": os.path.relpath(ev_path, results_dir) if os.path.exists(ev_path) else None,
           **res}
    return rec


def run_one_with_retry(arm, row, results_dir, mock, embedder):
    attempts = []
    rec = None
    for attempt in range(1 + INFRA_RETRIES):
        rec = run_one(arm, row, results_dir, mock, embedder, attempt)
        attempts.append({
            "attempt": attempt + 1,
            "failure_category": rec.get("failure_category"),
            "cost_usd": rec.get("cost_usd", 0.0),
            "error": (rec.get("error") or "")[:200],
            "events_file": rec.get("events_file"),
        })
        if rec.get("failure_category") in INFRA_FAILURES and attempt < INFRA_RETRIES:
            time.sleep(RETRY_BACKOFF_S * (attempt + 1))
            continue
        break
    rec["attempts_info"] = attempts
    rec["attempts"] = len(attempts)
    rec["cost_usd_total_attempts"] = round(sum(a["cost_usd"] for a in attempts), 6)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["dry_run", "full", "confirmatory"])
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=0)
    args = ap.parse_args()

    results_dir = os.environ.get("RESULTS_DIR") or os.path.join(C.ROOT, "07_results", "raw", "_manual")
    os.makedirs(results_dir, exist_ok=True)

    # D-013 Phase 1.2：启动前模型锁（FAIL CLOSED，非 mock 时）
    if not args.mock:
        got = {k: os.environ.get(v) for k, v in MODEL_ENV.items()}
        if got != FROZEN_MODEL:
            print(f"[model-lock] FAIL CLOSED: frozen={FROZEN_MODEL} got={got}", flush=True)
            sys.exit(2)
        print(f"[model-lock] OK: {FROZEN_MODEL}", flush=True)

    if args.phase == "confirmatory":
        manifest_path, sched_path, role, def_repeats = CONFIRMATORY_MANIFEST, CONFIRMATORY_SCHEDULE, "confirmatory", 3
    else:
        manifest_path, sched_path, role, def_repeats = C.MANIFEST, SCHEDULE, ("dry_run" if args.phase == "dry_run" else "mve"), (1 if args.phase == "dry_run" else 2)
    rows = [r for r in C.load_manifest(manifest_path) if r["role"] == role]
    if args.limit:
        rows = rows[:args.limit]
    repeats = args.repeats or def_repeats
    sched = load_schedule(sched_path)
    embedder = FakeEmbedder() if args.mock else arms.FastEmbedder()
    if not args.mock:
        write_freeze_identity(results_dir)

    rec_path = os.path.join(results_dir, "records.jsonl")
    total_cost = _load_existing_cost(rec_path)
    n_done, hard_stop, guard_state = 0, False, "ok"
    summary = {"phase": args.phase, "mock": args.mock, "backend": "pi-rpc-deepseek-v4-pro-high" if not args.mock else "mock",
               "repeats": repeats, "schedule": os.path.relpath(sched_path, C.ROOT),
               "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "hard_stop": False,
               "cost_guard": {"expected": C.COST_EXPECTED_USD, "warning": C.COST_WARNING_USD,
                              "pause": C.COST_PAUSE_USD, "hard": C.COST_HARD_GUARD_USD,
                              "cumulative_start": round(total_cost, 6)}}
    for row in rows:
        order = sched.get(row["entry_id"], [])
        for rep, pos, arm in order:
            if rep > repeats:
                continue
            if not args.mock:
                if total_cost >= C.COST_HARD_GUARD_USD:
                    guard_state = "hard_stop"; break
                if total_cost >= C.COST_PAUSE_USD:
                    guard_state = "paused_at_75"; break
                if total_cost >= C.COST_WARNING_USD:
                    print(f"[cost guard] WARNING: cumulative ${total_cost:.2f} >= ${C.COST_WARNING_USD} (仅告警)", flush=True)
            r = dict(row)
            r["_rep"] = rep
            rec = run_one_with_retry(arm, r, results_dir, args.mock, embedder)
            with open(rec_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            total_cost += rec.get("cost_usd_total_attempts", rec.get("cost_usd", 0.0))
            n_done += 1
            a = rec.get("accounting", {})
            print(f"[{n_done}] {rec['entry_id']} {arm} rep{rep}: fail={rec.get('failure_category')} "
                  f"A={a.get('A', 0)} B={a.get('B', 0)} C={a.get('C', 0)} R={a.get('R', 0)} "
                  f"cost=${rec.get('cost_usd_total_attempts', 0):.5f} cum=${total_cost:.5f} attempts={rec.get('attempts')}", flush=True)
            if rec.get("failure_category") == "infrastructure_error":
                guard_state = "infrastructure_error"
                print(f"[FAIL-CLOSED] infrastructure_error at {rec['entry_id']} {arm} rep{rep}: {rec.get('error')}", flush=True)
                break
        if guard_state != "ok":
            break
    summary.update({"total_cost_usd": round(total_cost, 6), "n_records": n_done, "hard_stop": hard_stop,
                    "guard_state": guard_state,
                    "finished_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    json.dump(summary, open(os.path.join(results_dir, "summary.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print(f"done: {n_done} records, cost ${total_cost:.6f}, guard={guard_state}")
    if guard_state == "infrastructure_error":
        return INDEX_INFRA_EXIT
    return 1 if (hard_stop or guard_state in ("hard_stop", "paused_at_75")) else 0


def _load_existing_cost(rec_path):
    total = 0.0
    if os.path.exists(rec_path):
        with open(rec_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += r.get("cost_usd_total_attempts", r.get("cost_usd", 0.0))
    return total


def write_freeze_identity(results_dir):
    """启动时写 freeze_identity.json：runtime commit + implementation + manifest sha + frozen hashes + model。"""
    # Same normalized text SHA256 as manifest generation and analysis (B1).
    sha = C.sha256_norm
    runtime = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    lm = json.load(open(C.LAUNCH_MANIFEST, encoding="utf-8"))
    ident = {
        "actual_runtime_git_commit": runtime,
        "implementation_commit": lm.get("implementation_commit"),
        "launch_manifest_sha256": sha(C.LAUNCH_MANIFEST),
        "config_sha256": sha(C.FROZEN_FILES["experiment_config"]),
        "sample_manifest_sha256": sha(C.FROZEN_FILES["sample_manifest"]),
        "schedule_sha256": sha(C.FROZEN_FILES["run_schedule"]),
        "index_manifest_sha256": sha(C.FROZEN_FILES["index_manifest"]),
        "evaluator_sha256": sha(C.FROZEN_FILES["evaluator"]),
        "provider": FROZEN_MODEL["provider"],
        "model": FROZEN_MODEL["model"],
        "reasoning": FROZEN_MODEL["thinking"],
    }
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, "freeze_identity.json"), "w", encoding="utf-8") as f:
        json.dump(ident, f, indent=2, ensure_ascii=False)
    return ident


if __name__ == "__main__":
    sys.exit(main())
