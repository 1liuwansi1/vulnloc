#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_confirmatory_analysis.py — D-013 Phase 3.7+3.8：confirmatory analysis 用纯 synthetic data 测试。

验证：run_id 拒绝逻辑、720-unit 完整性校验、冻结统计实现（primary/permutation/CI/subgroup/cluster）。
禁止使用 Attempt 1 真实 predictions。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import confirmatory_stats as CS
import analyze_c06_confirmatory as AC


def make_synthetic(n_entries=80, repeats=3):
    """生成 80 entries × 3 arms × 3 repeats 的合成 records + manifest。"""
    arms = ["agent", "rag", "pack"]
    manifest = {}
    records = []
    for i in range(n_entries):
        eid = f"entry-{i:04d}"
        cluster = "openclaw" if i < 45 else ("n8n" if i < 57 else f"other{i}")
        manifest[eid] = {"entry_id": eid, "ep_file": f"a_{i}.py", "ep_line": 100,
                         "co_file": f"b_{i}.py", "co_line": 200,
                         "path_hint": "PATH_HINT" if i % 3 == 0 else "NO_PATH_HINT",
                         "cluster_id": cluster, "project": cluster, "commit": "c" * 40}
        for arm in arms:
            for rep in range(1, repeats + 1):
                if arm == "agent":
                    cand = [{"path": f"a_{i}.py", "line_start": 100, "line_end": 100},
                            {"path": f"b_{i}.py", "line_start": 200, "line_end": 200}]
                elif arm == "pack":
                    cand = [{"path": f"a_{i}.py", "line_start": 100, "line_end": 100}]
                else:  # rag：60% 命中两个，40% 命中一个
                    cand = [{"path": f"a_{i}.py", "line_start": 100, "line_end": 100}] + \
                           ([{"path": f"b_{i}.py", "line_start": 200, "line_end": 200}] if i % 5 < 3 else [])
                records.append({"entry_id": eid, "arm": arm, "repeat": rep,
                                "answer": {"candidate_files": cand},
                                "failure_category": None,
                                "cost_usd_total_attempts": 0.05, "cost_usd": 0.05,
                                "wall_seconds": 60.0})
    sched = [(m["entry_id"], rep, arm) for m in manifest.values() for rep in range(1, repeats + 1) for arm in arms]
    return records, manifest, sched


def test_run_id_rejections():
    cases = [("c06-confirmatory-20260929T114451Z-bb50", False),  # Attempt 1
             ("c06-micro-mve-anything", False),                  # pilot
             ("random-run-id", False),                           # unknown
             ("c06-confirmatory-20260930T000000Z-abcd", True)]   # valid
    ok = all(AC.check_run_id(r)[0] == want for r, want in cases)
    return ok, "run_id 拒绝/接受逻辑"


def test_completeness():
    records, manifest, sched = make_synthetic()
    exp = {(e, rep, a) for e, rep, a in sched}
    # 有效 720
    ok, issues = AC.check_completeness(records, exp)
    if not ok:
        return False, f"有效 720 被拒: {issues}"
    # 719（缺 1）
    ok2, _ = AC.check_completeness(records[:-1], exp)
    # 重复 1
    dup = records + [records[0]]
    ok3, _ = AC.check_completeness(dup, exp)
    # infra error
    rec2 = [dict(r) for r in records]
    rec2[0]["failure_category"] = "infrastructure_error"
    ok4, _ = AC.check_completeness(rec2, exp)
    return (not ok2 and not ok3 and not ok4), f"719={not ok2} dup={not ok3} infra={not ok4}"


def test_stats():
    records, manifest, sched = make_synthetic()
    entries = sorted(manifest.keys())
    cluster_fn = lambda row: row.get("cluster_id")  # noqa: E731
    repo_fn = lambda row, rec: "/tmp"  # noqa: E731
    stats = CS.run_primary_and_secondary(records, manifest, entries, cluster_fn, repo_fn)
    p = stats["primary"]["agent_vs_pack"]
    # agent=1.0, pack=0.5 → mean ≈ 0.5，permutation_p 应极小（<0.001）
    ok = (abs(p["mean"] - 0.5) < 0.01 and p["permutation_p"] < 0.001
          and stats["primary"]["arm_means_fr"]["agent"] > stats["primary"]["arm_means_fr"]["pack"]
          and stats["cluster_sensitivity"]["dominant_cluster"] == "openclaw")
    return ok, f"primary mean={p['mean']} perm_p={p['permutation_p']} arms={stats['primary']['arm_means_fr']}"


def main():
    tests = [("run_id 拒绝", test_run_id_rejections),
             ("720 完整性", test_completeness),
             ("冻结统计", test_stats)]
    results = []
    for name, fn in tests:
        try:
            ok, detail = fn()
            results.append((name, ok, detail))
            print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
        except Exception as e:  # noqa: BLE001
            results.append((name, False, f"EXC {e}"))
            print(f"  [BAD] {name}: EXC {e}")
    allpass = all(ok for _, ok, _ in results)
    print(f"\nCONFIRMATORY ANALYSIS PIPELINE: {'PASS' if allpass else 'FAIL'}")
    out = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_analysis_test.json")
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
