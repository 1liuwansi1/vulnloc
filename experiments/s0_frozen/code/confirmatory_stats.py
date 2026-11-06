#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
confirmatory_stats.py — C-06 confirmatory 冻结统计实现（D-013 Phase 3.8）。

统计单位 = entry（3 repeats 先 entry 内聚合，禁止把 80×3=240 当独立样本）。
PRIMARY: Agent vs Pack / File Recall@5，bootstrap 10k(seed 20260928) percentile CI +
         permutation sign-flip Monte Carlo 100k(seed 20260928) 为主 + Wilcoxon(平均秩) 辅助。
SECONDARY: Line Recall@5、Agent vs RAG、RAG vs Pack、invalid path rate、PATH_HINT 交互、
           leave-openclaw-out、cluster-aware 敏感性、repeat 稳定性、cost/latency。
Multiple-testing: BH-FDR（secondary 家族）。
纯函数，不依赖真实数据（可用 synthetic data 测试）。
"""
import json
import math
import random
import statistics


def entry_level(records, manifest_by_entry, metric_fn):
    """entry 内 repeats 聚合：{entry_id: {arm: mean_metric}}。"""
    acc = {}
    for rec in records:
        e = rec["entry_id"]
        arm = rec["arm"]
        v = metric_fn(manifest_by_entry.get(e), rec.get("answer"))
        acc.setdefault(e, {}).setdefault(arm, []).append(v)
    out = {}
    for e, arms in acc.items():
        out[e] = {a: statistics.mean(vs) for a, vs in arms.items()}
    return out


def paired_diffs(entry_mean, arm_a, arm_b, entries):
    return [entry_mean[e][arm_a] - entry_mean[e][arm_b] for e in entries
            if arm_a in entry_mean[e] and arm_b in entry_mean[e]]


def bootstrap_ci(d, n_iter=10000, seed=20260928):
    rng = random.Random(seed)
    n = len(d)
    means = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_iter))
    return [round(means[int(0.025 * n_iter)], 4), round(means[int(0.975 * n_iter)], 4)]


def permutation_p(d, n_iter=100000, seed=20260928):
    rng = random.Random(seed)
    nz = [x for x in d if x != 0]
    if not nz:
        return 1.0
    obs = abs(sum(nz))
    greater = sum(1 for _ in range(n_iter)
                  if abs(sum(x if rng.random() < 0.5 else -x for x in nz)) >= obs - 1e-12)
    return round((greater + 1) / (n_iter + 1), 4)


def wilcoxon_p(d):
    nz = [x for x in d if x != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    abs_vals = [abs(x) for x in nz]
    order = sorted(range(n), key=lambda i: abs_vals[i])
    ranks = [0.0] * n
    i = 0
    tie_sum = 0.0
    while i < n:
        j = i
        while j < n and abs_vals[order[j]] == abs_vals[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[order[k]] = avg
        t = j - i
        tie_sum += t ** 3 - t
        i = j
    W = sum(ranks[k] for k in range(n) if nz[k] > 0)
    meanW = n * (n + 1) / 4.0
    varW = n * (n + 1) * (2 * n + 1) / 24.0 - tie_sum / 48.0
    if varW <= 0:
        return 1.0
    z = (W - meanW) / math.sqrt(varW)
    return round(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))), 4)


def cohens_dz(d):
    """Cohen's d_z = mean / sample SD（ddof=1，与 evaluate.py 口径一致）。"""
    n = len(d)
    if n < 2:
        return 0.0
    m = statistics.mean(d)
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    sd = var ** 0.5
    return round(m / sd, 4) if sd > 1e-9 else 0.0


def bh_fdr(pvalues):
    """Benjamini-Hochberg FDR（reverse cumulative minimum，标准实现）。返回 q 值（原顺序）。"""
    n = len(pvalues)
    if n == 0:
        return []
    idx = sorted(range(n), key=lambda i: pvalues[i])
    q_sorted = [0.0] * n
    running = 1.0
    for rank in range(n - 1, -1, -1):
        i = idx[rank]
        q = pvalues[i] * n / (rank + 1)
        running = min(running, q)
        q_sorted[rank] = running
    qvals = [0.0] * n
    for rank, i in enumerate(idx):
        qvals[i] = min(1.0, q_sorted[rank])
    return qvals


def invalid_path_rate(records, manifest_by_entry, repo_dir_fn):
    per_arm = {}
    for rec in records:
        arm = rec["arm"]
        repo = repo_dir_fn(manifest_by_entry.get(rec["entry_id"]), rec)
        ans = rec.get("answer") or {}
        tot = bad = 0
        for c in ans.get("candidate_files", []):
            p = c.get("path") if isinstance(c, dict) else None
            if p:
                tot += 1
                import os
                if not os.path.exists(os.path.join(repo, p)):
                    bad += 1
        a = per_arm.setdefault(arm, [0, 0])
        a[0] += bad
        a[1] += tot
    return {arm: {"bad": v[0], "total": v[1], "rate": round(v[0] / v[1], 4) if v[1] else 0.0}
            for arm, v in per_arm.items()}


def repeat_stability(records, manifest_by_entry, metric_fn):
    """repeat 级稳定性：每 (entry, arm) 的 repeat 间 |diff|。"""
    acc = {}
    for rec in records:
        e = rec["entry_id"]
        arm = rec["arm"]
        v = metric_fn(manifest_by_entry.get(e), rec.get("answer"))
        acc.setdefault((e, arm), []).append(v)
    diffs = [abs(max(vs) - min(vs)) for vs in acc.values() if len(vs) > 1]
    return {"mean_abs_diff": round(statistics.mean(diffs), 4) if diffs else 0.0,
            "median_abs_diff": round(statistics.median(diffs), 4) if diffs else 0.0,
            "n_cells": len(diffs)}


def run_primary_and_secondary(records, manifest_by_entry, entries, cluster_id_fn, repo_dir_fn):
    """完整冻结统计。返回 stats dict。"""
    from collections import defaultdict
    fr = lambda row, ans: file_recall(row, ans)  # noqa: E731
    lr = lambda row, ans: line_recall(row, ans)  # noqa: E731

    em_fr = entry_level(records, manifest_by_entry, fr)
    em_lr = entry_level(records, manifest_by_entry, lr)

    arms = ["agent", "rag", "pack"]

    def paired(em, a, b, subset):
        d = []
        for e in subset:
            if a in em.get(e, {}) and b in em.get(e, {}):
                d.append(em[e][a] - em[e][b])
        return d

    stats = {"primary": {}, "secondary": {}, "subgroups": {}, "cluster_sensitivity": {},
             "repeat_stability": {}, "cost_latency": {}, "invalid_path": {}}

    # PRIMARY: agent vs pack, FR@5
    d = paired(em_fr, "agent", "pack", entries)
    stats["primary"]["agent_vs_pack"] = {
        "n": len(d), "mean": round(statistics.mean(d), 4) if d else None,
        "bootstrap_ci95": bootstrap_ci(d) if d else None,
        "cohens_dz": cohens_dz(d) if d else None,
        "permutation_p": permutation_p(d) if d else None,
        "wilcoxon_p": wilcoxon_p(d) if d else None,
    }
    # 各臂均值
    stats["primary"]["arm_means_fr"] = {a: round(statistics.mean([em_fr[e][a] for e in entries if a in em_fr.get(e, {})]), 4) for a in arms}

    # SECONDARY family（冻结 statistical_plan.md 严格 4 成员：对比=Agent-RAG、RAG-Pack；指标=FR@5、LineRecall@5）
    # 说明：Invalid Path Rate 与 PATH_HINT 交互为描述性（无 p-value），不入 BH family（见下）。
    sec_members = [("fr_agent_vs_rag", em_fr, "agent", "rag"),
                   ("fr_rag_vs_pack", em_fr, "rag", "pack"),
                   ("lr_agent_vs_rag", em_lr, "agent", "rag"),
                   ("lr_rag_vs_pack", em_lr, "rag", "pack")]
    for k, em, a, b in sec_members:
        d = paired(em, a, b, entries)
        stats["secondary"][k] = {"n": len(d), "mean": round(statistics.mean(d), 4) if d else None,
                                 "bootstrap_ci95": bootstrap_ci(d) if d else None,
                                 "cohens_dz": cohens_dz(d) if d else None,
                                 "permutation_p": permutation_p(d) if d else None,
                                 "wilcoxon_p": wilcoxon_p(d) if d else None}
    stats["secondary"]["arm_means_lr"] = {a: round(statistics.mean([em_lr[e][a] for e in entries if a in em_lr.get(e, {})]), 4) for a in arms}

    # BH-FDR across secondary family（5 成员）
    member_names = [k for k, _, _, _ in sec_members]
    pvals = [stats["secondary"][k]["permutation_p"] for k in member_names]
    qvals = bh_fdr(pvals)
    stats["secondary"]["bh_fdr_qvalues"] = dict(zip(member_names, qvals))
    stats["secondary"]["bh_family_members"] = member_names

    # invalid path rate
    stats["invalid_path"] = invalid_path_rate(records, manifest_by_entry, repo_dir_fn)

    # PATH_HINT / NO_PATH_HINT subgroup
    ph_entries = [e for e in entries if manifest_by_entry[e].get("path_hint") == "PATH_HINT"]
    np_entries = [e for e in entries if manifest_by_entry[e].get("path_hint") == "NO_PATH_HINT"]
    for name, subset in (("PATH_HINT", ph_entries), ("NO_PATH_HINT", np_entries)):
        d_ap = paired(em_fr, "agent", "pack", subset)
        arm_means = {}
        for a in arms:
            vs = [em_fr[e][a] for e in subset if a in em_fr.get(e, {})]
            arm_means[a] = round(statistics.mean(vs), 4) if vs else None
        stats["subgroups"][name] = {
            "n": len(subset),
            "agent_vs_pack": {"mean": round(statistics.mean(d_ap), 4) if d_ap else None,
                              "bootstrap_ci95": bootstrap_ci(d_ap) if d_ap else None,
                              "permutation_p": permutation_p(d_ap) if d_ap else None},
            "arm_means_fr": arm_means,
        }

    # cluster-aware 敏感性：leave-one-cluster-out（全部 cluster）+ cluster-level 描述性聚合
    clusters = defaultdict(list)
    for e in entries:
        clusters[cluster_id_fn(manifest_by_entry[e])].append(e)
    oc = max(clusters, key=lambda c: len(clusters[c]))
    leave_one_out = {}
    for c in sorted(clusters, key=lambda x: -len(clusters[x])):
        subset = [e for e in entries if cluster_id_fn(manifest_by_entry[e]) != c]
        d_ap = paired(em_fr, "agent", "pack", subset)
        leave_one_out[c] = {"n": len(subset),
                            "mean": round(statistics.mean(d_ap), 4) if d_ap else None,
                            "bootstrap_ci95": bootstrap_ci(d_ap) if d_ap else None,
                            "permutation_p": permutation_p(d_ap) if d_ap else None}
    # cluster-level 聚合（描述性，n=cluster 数，不作 confirmatory）
    cluster_means = {}
    for c, es in clusters.items():
        for arm in arms:
            vs = [em_fr[e][arm] for e in es if arm in em_fr.get(e, {})]
            cluster_means.setdefault(c, {})[arm] = round(statistics.mean(vs), 4) if vs else None
    non_oc = [e for e in entries if cluster_id_fn(manifest_by_entry[e]) != oc]
    d_ap_nooc = paired(em_fr, "agent", "pack", non_oc)
    stats["cluster_sensitivity"] = {
        "dominant_cluster": oc, "dominant_n": len(clusters[oc]),
        "n_clusters": len(clusters),
        "leave_dominant_out_n": len(non_oc),
        "leave_dominant_out_agent_vs_pack": {
            "mean": round(statistics.mean(d_ap_nooc), 4) if d_ap_nooc else None,
            "bootstrap_ci95": bootstrap_ci(d_ap_nooc) if d_ap_nooc else None,
            "permutation_p": permutation_p(d_ap_nooc) if d_ap_nooc else None},
        "leave_one_out": leave_one_out,
        "cluster_level_aggregation": cluster_means,
        "cluster_sizes": {c: len(v) for c, v in sorted(clusters.items(), key=lambda x: -len(x[1]))},
    }

    # repeat 稳定性
    stats["repeat_stability"] = repeat_stability(records, manifest_by_entry, fr)

    # cost / latency 臂均值
    cost = defaultdict(list)
    lat = defaultdict(list)
    for rec in records:
        cost[rec["arm"]].append(rec.get("cost_usd_total_attempts", rec.get("cost_usd", 0.0)))
        lat[rec["arm"]].append(rec.get("wall_seconds", 0.0))
    stats["cost_latency"] = {a: {"cost_mean": round(statistics.mean(cost[a]), 6) if cost[a] else 0.0,
                                 "latency_mean_s": round(statistics.mean(lat[a]), 1) if lat[a] else 0.0}
                             for a in arms}

    return stats


def file_recall(row, answer):
    if not answer:
        return 0.0
    targets = {x for x in (row["ep_file"], row["co_file"]) if x}
    if not targets:
        return 0.0
    preds = {c["path"] for c in answer.get("candidate_files", [])[:5] if isinstance(c, dict) and c.get("path")}
    return len(targets & preds) / len(targets)


def line_recall(row, answer):
    if not answer:
        return 0.0
    def parse(v):
        s = str(v).strip()
        try:
            if "-" in s:
                a, b = s.split("-")[:2]
                return int(a), int(b)
            return int(s), int(s)
        except (ValueError, IndexError):
            return None, None
    locs = [(row["ep_file"], parse(row["ep_line"])), (row["co_file"], parse(row["co_line"]))]
    hits = 0
    for f, (t0, t1) in locs:
        if t0 is None:
            continue
        for c in answer.get("candidate_files", []):
            if not isinstance(c, dict) or c.get("path") != f:
                continue
            s, e = c.get("line_start"), c.get("line_end")
            if isinstance(s, int) and isinstance(e, int) and (s - 5) <= t1 and (e + 5) >= t0:
                hits += 1
                break
    return hits / 2.0
