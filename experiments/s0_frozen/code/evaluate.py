#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate.py — C-06 指标计算（arm 盲）。File Recall@5 / Line Recall@5 / 记账 / 一致性 / 效应量。"""
import json
import os
import random

import common as C


def file_recall(row, answer):
    if not answer:
        return 0.0
    targets = {x for x in (row["ep_file"], row["co_file"]) if x}
    if not targets:
        return 0.0
    preds = {c["path"] for c in answer.get("candidate_files", [])[:5] if isinstance(c, dict) and c.get("path")}
    return len(targets & preds) / len(targets)


def _parse_lines(v):
    """VulnGym 行标注可能是单行或范围（如 '493-494'）。返回 (lo, hi) 或 (None, None)。"""
    s = str(v).strip()
    try:
        if '-' in s:
            a, b = s.split('-')[:2]
            return int(a), int(b)
        return int(s), int(s)
    except (ValueError, IndexError):
        return None, None


def line_recall(row, answer):
    if not answer:
        return 0.0
    locs = [(row["ep_file"], _parse_lines(row["ep_line"])),
            (row["co_file"], _parse_lines(row["co_line"]))]
    hits = 0
    for f, (t0, t1) in locs:
        if t0 is None:
            continue
        for c in answer.get("candidate_files", []):
            if not isinstance(c, dict):
                continue
            if c.get("path") == f:
                s, e = c.get("line_start"), c.get("line_end")
                if isinstance(s, int) and isinstance(e, int) and (s - 5) <= t1 and (e + 5) >= t0:
                    hits += 1
                    break
    return hits / 2.0


def packed_coverage(row, record):
    """pack 臂：ground-truth 文件是否落在打包窗口（content delivered）。"""
    if record.get("arm") != "pack":
        return None
    paths = {b["path"] for b in record.get("blocks", []) if b.get("kind") == "pack"}
    t = {x for x in (row["ep_file"], row["co_file"]) if x}
    if not t:
        return 1.0
    return len(t & paths) / len(t)


def pred_path_existence(row, record):
    """预测路径是否真实存在（hallucination/记忆漂移检查）。"""
    repo = C.repo_dir(row["project"], row["commit"])
    ans = record.get("answer")
    if not ans:
        return None
    out = []
    for c in ans.get("candidate_files", []):
        p = c.get("path")
        out.append({"path": p, "exists": bool(p and os.path.isfile(os.path.join(repo, p)))})
    return out


def aggregate(records, manifest):
    gt = {r["entry_id"]: r for r in manifest}
    per_rec = []
    for rec in records:
        row = gt.get(rec["entry_id"])
        if row is None:
            continue
        ans = rec.get("answer")
        per_rec.append({
            "entry_id": rec["entry_id"], "arm": rec["arm"], "repeat": rec["repeat"],
            "file_recall5": file_recall(row, ans),
            "line_recall5": line_recall(row, ans),
            "failure_category": rec.get("failure_category"),
            "A": rec.get("accounting", {}).get("A", 0),
            "A_unique": rec.get("accounting", {}).get("A_unique", 0),
            "B": rec.get("accounting", {}).get("B", 0),
            "C": rec.get("accounting", {}).get("C", 0),
            "R": rec.get("accounting", {}).get("R", 0),
            "D": rec.get("accounting", {}).get("D", 0),
            "F": rec.get("accounting", {}).get("F", 0),
            "cost_usd": rec.get("cost_usd", 0.0),
            "coverage": packed_coverage(row, rec),
            "pred_existence": pred_path_existence(row, rec),
        })
    arms = ["agent", "rag", "pack"]
    by_arm = {}
    for a in arms:
        rs = [r for r in per_rec if r["arm"] == a]
        if not rs:
            by_arm[a] = {"n": 0}
            continue
        n = len(rs)
        by_arm[a] = {
            "n": n,
            "file_recall5_mean": sum(r["file_recall5"] for r in rs) / n,
            "line_recall5_mean": sum(r["line_recall5"] for r in rs) / n,
            "A_mean": sum(r["A"] for r in rs) / n,
            "B_mean": sum(r["B"] for r in rs) / n,
            "C_mean": sum(r["C"] for r in rs) / n,
            "R_mean": sum(r["R"] for r in rs) / n,
            "D_mean": sum(r["D"] for r in rs) / n,
            "F_mean": sum(r["F"] for r in rs) / n,
            "cost_mean": sum(r["cost_usd"] for r in rs) / n,
            "failure_counts": {fc: sum(1 for r in rs if r["failure_category"] == fc)
                               for fc in {r["failure_category"] for r in rs}},
        }
    # per-entry mean over repeats, then paired diffs
    entry_mean = {}
    for r in per_rec:
        entry_mean.setdefault((r["entry_id"], r["arm"]), []).append(r["file_recall5"])
    em = {(e, a): sum(v) / len(v) for (e, a), v in entry_mean.items()}
    entries = sorted({e for e, _ in entry_mean})
    diffs = {"agent-rag": [], "agent-pack": [], "rag-pack": []}
    for e in entries:
        v = {a: em.get((e, a)) for a in arms}
        if all(x is not None for x in v.values()):
            diffs["agent-rag"].append(v["agent"] - v["rag"])
            diffs["agent-pack"].append(v["agent"] - v["pack"])
            diffs["rag-pack"].append(v["rag"] - v["pack"])
    stats = {"by_arm": by_arm, "paired_diffs": {}}
    for k, d in diffs.items():
        if not d:
            stats["paired_diffs"][k] = {"n": 0}
            continue
        stats["paired_diffs"][k] = {
            "n": len(d), "mean": sum(d) / len(d),
            "bootstrap_ci95": bootstrap_ci(d),
            "cohens_dz": cliffs_delta(d),
            "wilcoxon_p_avg_rank": wilcoxon_p(d),
            "permutation_p": permutation_p(d),
            "sign_consistency": direction_consistent(d),
        }
    return {"per_record": per_rec, "stats": stats}


def bootstrap_ci(d, n_iter=10000, seed=0):
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        sample = [d[rng.randrange(len(d))] for _ in range(len(d))]
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    return [round(lo, 4), round(hi, 4)]


def cliffs_delta(d):
    """配对差异的标准化效应量（Cohen's d_z = mean/std）。d 为配对差异向量。"""
    n = len(d)
    if n < 2:
        return 0.0
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1)
    sd = var ** 0.5
    return round(mean / sd, 4) if sd > 1e-9 else 0.0


def wilcoxon_p(d):
    """Wilcoxon signed-rank 双尾 p（平均秩处理 tie + tie-adjusted 方差）。"""
    import math
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
        avg = (i + 1 + j) / 2.0  # 1-based 平均秩
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
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return round(p, 4)


def permutation_p(d, n_iter=100000, seed=20260928):
    """精确配对随机化检验（H0 下差异符号随机翻转）。双尾 p。seed 冻结。"""
    import random
    rng = random.Random(seed)
    nz = [x for x in d if x != 0]
    n = len(nz)
    if n == 0:
        return 1.0
    obs = abs(sum(nz))
    greater = 0
    for _ in range(n_iter):
        s = sum(x if rng.random() < 0.5 else -x for x in nz)
        if abs(s) >= obs - 1e-12:
            greater += 1
    return round((greater + 1) / (n_iter + 1), 4)


def direction_consistent(d):
    """非零配对差异中与多数符号一致的比例（0..1）；描述性，不作 confirmatory。"""
    nz = [x for x in d if x != 0]
    if not nz:
        return 0.0
    pos = sum(1 for x in nz if x > 0)
    return round(max(pos, len(nz) - pos) / len(nz), 4)
