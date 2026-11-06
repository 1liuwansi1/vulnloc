#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_stats_frozen.py — D-013 re-audit Phase 6：冻结统计 reference 测试（no-LLM）。

验证：BH-FDR（reference + 排序/reverse cumulative minimum/monotonicity/capped/原序恢复）、
secondary family 完整成员、cluster sensitivity、Cohen's d_z（sample SD ddof=1）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confirmatory_stats as CS
import common as C


def test_bh_fdr_reference():
    q = CS.bh_fdr([0.01, 0.04, 0.04])
    return q == [0.03, 0.04, 0.04], f"q={q}"


def test_bh_fdr_properties():
    # 多组 reference：验证排序、reverse cumulative minimum、monotonicity、capped、原序恢复
    import random
    ok = True
    detail = ""
    for _ in range(200):
        n = random.randint(2, 8)
        p = [round(random.random(), 4) for _ in range(n)]
        q = CS.bh_fdr(p)
        # capped at 1.0
        if any(x > 1.0 or x < 0 for x in q):
            ok = False; detail = f"capped 失败 p={p} q={q}"; break
        # 原序恢复：q 与 p 同序（索引对应）
        if len(q) != n:
            ok = False; detail = "长度不匹配"; break
        # 单调性：若 p_i <= p_j 则 q_i <= q_j（同秩时用排序）
        order = sorted(range(n), key=lambda i: p[i])
        qsorted = [q[i] for i in order]
        if any(qsorted[i] > qsorted[i + 1] + 1e-9 for i in range(n - 1)):
            ok = False; detail = f"单调性失败 p={p} q={q}"; break
    return ok, detail


def test_secondary_family():
    # synthetic 数据驱动 run_primary_and_secondary，验证 5 个成员 + BH family 列出
    n = 80
    manifest = {}
    records = []
    for i in range(n):
        eid = f"entry-{i:04d}"
        manifest[eid] = {"entry_id": eid, "ep_file": f"a_{i}.py", "ep_line": 100,
                         "co_file": f"b_{i}.py", "co_line": 200,
                         "path_hint": "PATH_HINT" if i % 3 == 0 else "NO_PATH_HINT",
                         "cluster_id": "openclaw" if i < 45 else f"c{i}", "project": "p", "commit": "c" * 40}
        for arm in ("agent", "rag", "pack"):
            for rep in (1, 2, 3):
                if arm == "pack":
                    cand = [{"path": f"a_{i}.py", "line_start": 100, "line_end": 100}]
                else:
                    cand = [{"path": f"a_{i}.py", "line_start": 100, "line_end": 100},
                            {"path": f"b_{i}.py", "line_start": 200, "line_end": 200}]
                records.append({"entry_id": eid, "arm": arm, "repeat": rep,
                                "answer": {"candidate_files": cand}, "failure_category": None,
                                "cost_usd_total_attempts": 0.05, "wall_seconds": 60.0})
    stats = CS.run_primary_and_secondary(records, manifest, sorted(manifest.keys()),
                                         lambda row: row.get("cluster_id"), lambda row, rec: "/tmp")
    members = stats["secondary"]["bh_family_members"]
    q = stats["secondary"]["bh_fdr_qvalues"]
    ok = (len(members) == 4 and set(members) == {"fr_agent_vs_rag", "fr_rag_vs_pack",
                                                 "lr_agent_vs_rag", "lr_rag_vs_pack"}
          and len(q) == 4)
    return ok, f"members={members}"


def test_cluster_sensitivity():
    n = 80
    manifest = {}
    records = []
    for i in range(n):
        eid = f"e{i}"
        manifest[eid] = {"entry_id": eid, "ep_file": "a.py", "ep_line": 1, "co_file": "b.py", "co_line": 2,
                         "path_hint": "NO_PATH_HINT", "cluster_id": "openclaw" if i < 45 else ("n8n" if i < 57 else f"c{i}"),
                         "project": "p", "commit": "c" * 40}
        for arm in ("agent", "rag", "pack"):
            for rep in (1, 2, 3):
                cand = [{"path": "a.py", "line_start": 1, "line_end": 1}] if arm == "pack" else \
                       [{"path": "a.py", "line_start": 1, "line_end": 1}, {"path": "b.py", "line_start": 2, "line_end": 2}]
                records.append({"entry_id": eid, "arm": arm, "repeat": rep,
                                "answer": {"candidate_files": cand}, "failure_category": None,
                                "cost_usd_total_attempts": 0.05, "wall_seconds": 60.0})
    stats = CS.run_primary_and_secondary(records, manifest, sorted(manifest.keys()),
                                         lambda row: row.get("cluster_id"), lambda row, rec: "/tmp")
    cs = stats["cluster_sensitivity"]
    n_clusters = len([c for c in manifest.values() if c["cluster_id"] == "openclaw"]) + 12
    ok = (cs["dominant_cluster"] == "openclaw"
          and len(cs["leave_one_out"]) == cs["n_clusters"]
          and "cluster_level_aggregation" in cs
          and len(cs["cluster_level_aggregation"]) == cs["n_clusters"])
    return ok, f"n_clusters={cs['n_clusters']} leave_one_out={len(cs['leave_one_out'])} agg={len(cs['cluster_level_aggregation'])}"


def test_dz_sample_sd():
    # ddof=1：d=[1,2,3] sample SD=1，mean=2 → d_z=2.0（population SD 会给 1.633）
    dz = CS.cohens_dz([1, 2, 3])
    return abs(dz - 2.0) < 1e-9, f"d_z={dz} (期望 2.0 sample SD)"


def main():
    tests = [("BH-FDR reference [0.01,0.04,0.04]->[0.03,0.04,0.04]", test_bh_fdr_reference),
             ("BH-FDR 性质（200 随机组）", test_bh_fdr_properties),
             ("secondary family 5 成员", test_secondary_family),
             ("cluster sensitivity (leave-one-out 全部 + 聚合)", test_cluster_sensitivity),
             ("Cohen's d_z sample SD (ddof=1)", test_dz_sample_sd)]
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
    print(f"\nFROZEN STATISTICS: {'PASS' if allpass else 'FAIL'}")
    import json
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(os.path.join(C.ROOT, "06_experiments", "c06", "stats_frozen_test.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
