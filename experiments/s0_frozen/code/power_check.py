#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
power_check.py — D-011B Step 7：power / precision 检查（N=80, 3 repeats, repo clustering）。

基于 pilot 的 entry-level paired SD（agent-pack 0.414, agent-rag 0.339）外推 CI 精度与
可检测效应。统计单位=entry（3 repeats 先 entry 内聚合）。不得以 pilot 大效应作为唯一依据。
"""
import math
import statistics
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C, evaluate

RECS = [json.loads(l) for l in open(glob.glob(os.path.join(C.ROOT, "07_results/raw/c06-micro-mve-*/records.jsonl"))[0])]
MAN = {r["entry_id"]: r for r in C.load_manifest()}
entries = sorted(e for e, r in MAN.items() if r["role"] == "mve")

def fr(r): return evaluate.file_recall(MAN[r["entry_id"]], r.get("answer"))
def paired(a, b):
    d = []
    for e in entries:
        va = statistics.mean([fr(r) for r in RECS if r["arm"] == a and r["entry_id"] == e])
        vb = statistics.mean([fr(r) for r in RECS if r["arm"] == b and r["entry_id"] == e])
        d.append(va - vb)
    return d

d_ap = paired("agent", "pack"); d_ar = paired("agent", "rag")
sd_ap = statistics.pstdev(d_ap); sd_ar = statistics.pstdev(d_ar)
print(f"pilot entry-level SD: agent-pack={sd_ap:.3f} agent-rag={sd_ar:.3f}")
print(f"pilot observed effect: agent-pack={statistics.mean(d_ap):.3f} agent-rag={statistics.mean(d_ar):.3f}")

MMD = 0.10   # 最小有意义差异：每 5 条 entry 多定位 1 个目标文件（FR@5 0.1）
TRIV = 0.02  # 视为平凡的差异

def t975(n):
    # 近似（n>=30）
    return 1.96 + 2.4/(n-1)

print(f"\nMMD={MMD}（有意义）, trivial≤{TRIV}")
for N in (60, 80, 100, 140, 178):
    se = sd_ap / math.sqrt(N)
    ci_half = t975(N) * se
    # 80% power 可检测效应 δ = (z975+z80)*se
    delta = (1.96 + 0.8416) * se
    # power to detect MMD
    z = MMD / se - 1.96
    power = 0.5*(1+math.erf(z/math.sqrt(2)))
    print(f"  N={N:3d}: CI半宽(ap)={ci_half:.3f} | 80%power可检测δ={delta:.3f} | MMD={MMD}的power={power:.2f} | 观测效应0.26的CI=[{0.2625-ci_half:.2f},{0.2625+ci_half:.2f}]")

# repo clustering：13 clusters，openclaw 主导。cluster 级聚合（描述性，n=13）
print("\n=== repo clustering 敏感性（描述性）===")
print("  13 clusters, openclaw ~48/80。cluster-robust 有效样本受 cluster 数上限约束。")
print("  计划：(a) 主分析 pooled n=80；(b) 敏感性1 leave-openclaw-out；(c) 敏感性2 cluster-级聚合(n=13, 仅描述)。")
