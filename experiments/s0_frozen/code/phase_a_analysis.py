#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
phase_a_analysis.py — C-06 full-experiment prep（零新增 API 成本，pilot 120 runs 冻结）。

冻结分类规则（先于分析固定）:
  PATH_HINT: advisory description 匹配（忽略大小写）:
    R1: /[\w\-./]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql|css|html)
    R2: \b[\w\-]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql)\b
  熟悉度（EXPLORATORY 代理，非污染证明）: FAMOUS 顶级知名项目；LESSER 其余。
"""
import csv
import json
import glob
import math
import os
import random
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import evaluate

ROOT = C.ROOT
RECS = [json.loads(l) for l in open(glob.glob(os.path.join(ROOT, "07_results/raw/c06-micro-mve-*/records.jsonl"))[0], encoding="utf-8")]
MAN = {r["entry_id"]: r for r in C.load_manifest()}

R1 = re.compile(r"/[\w\-./]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql|css|html)", re.I)
R2 = re.compile(r"\b[\w\-]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql)\b", re.I)
FAMOUS = {"openclaw", "n8n-io/n8n", "FlowiseAI/Flowise", "NVIDIA/NeMo", "milvus-io/milvus",
          "langflow-ai/langflow", "ollama/ollama", "apache/airflow", "onnx/onnx", "mlflow/mlflow",
          "langchain-ai/langchain", "open-webui/open-webui"}


def path_hint(row):
    d = row["task_description"].lower()
    return bool(R1.search(d) or R2.search(d))


def fr(r):
    return evaluate.file_recall(MAN[r["entry_id"]], r.get("answer"))


def lr(r):
    return evaluate.line_recall(MAN[r["entry_id"]], r.get("answer"))


entries = sorted(e for e, row in MAN.items() if row["role"] == "mve")

with open(os.path.join(ROOT, "06_experiments/c06/entry_classification.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["entry_id", "path_hint", "familiarity"])
    for e in entries:
        w.writerow([e, "PATH_HINT" if path_hint(MAN[e]) else "NO_PATH_HINT",
                    "FAMOUS" if MAN[e]["project"] in FAMOUS else "LESSER"])
cls = {row["entry_id"]: row for row in csv.DictReader(open(os.path.join(ROOT, "06_experiments/c06/entry_classification.csv"), encoding="utf-8"))}


def arm_vals(arm, subset, m):
    return [m(r) for r in RECS if r["arm"] == arm and r["entry_id"] in subset]


def paired(subset, a, b, m):
    d = []
    for e in subset:
        va = statistics.mean([m(r) for r in RECS if r["arm"] == a and r["entry_id"] == e])
        vb = statistics.mean([m(r) for r in RECS if r["arm"] == b and r["entry_id"] == e])
        d.append(va - vb)
    return d


def boot_ci(d, n_iter=10000, seed=0):
    if len(d) < 2:
        return (0, 0)
    rng = random.Random(seed)
    ms = sorted(sum(d[rng.randrange(len(d))] for _ in range(len(d))) / len(d) for _ in range(n_iter))
    return round(ms[250], 3), round(ms[9750], 3)


def report(name, subset):
    print(f"\n### {name}（entries={len(subset)}）")
    for a in ("agent", "rag", "pack"):
        f = arm_vals(a, subset, fr)
        l = arm_vals(a, subset, lr)
        print(f"  {a:6s}: FR@5={statistics.mean(f):.3f} (n={len(f)})  LR@5={statistics.mean(l):.3f}")
    for k, a, b in (("agent-rag", "agent", "rag"), ("agent-pack", "agent", "pack"), ("rag-pack", "rag", "pack")):
        d = paired(subset, a, b, fr)
        m = statistics.mean(d)
        sd = statistics.pstdev(d)
        dz = m / sd if sd > 0 else 0
        ci = boot_ci(d)
        print(f"  {k}: mean={m:.3f} 95%CI={ci} dz={dz:.2f}")


print("=== PHASE A1: PATH-HINT 分层 ===")
ph = [e for e in entries if cls[e]["path_hint"] == "PATH_HINT"]
np_ = [e for e in entries if cls[e]["path_hint"] == "NO_PATH_HINT"]
print(f"PATH_HINT={len(ph)}, NO_PATH_HINT={len(np_)}")
report("PATH_HINT", ph)
report("NO_PATH_HINT", np_)

print("\n=== PHASE A2: 熟悉度审计（EXPLORATORY）===")
fam = [e for e in entries if cls[e]["familiarity"] == "FAMOUS"]
les = [e for e in entries if cls[e]["familiarity"] == "LESSER"]
print(f"FAMOUS={len(fam)}, LESSER={len(les)}")
for a in ("agent", "rag", "pack"):
    ff = statistics.mean(arm_vals(a, fam, fr))
    ll = statistics.mean(arm_vals(a, les, fr))
    print(f"  {a:6s}: FAMOUS={ff:.3f} (n={len(fam)*2})  LESSER={ll:.3f} (n={len(les)*2})")

print("\n=== PHASE A3: 路径有效性（EXPLORATORY DISCOVERY）===")
for a in ("agent", "rag", "pack"):
    tot = bad = 0
    for r in RECS:
        if r["arm"] != a:
            continue
        repo = C.repo_dir(r["project"], r["commit"])
        for c in (r.get("answer") or {}).get("candidate_files", []):
            p = c.get("path")
            if p:
                tot += 1
                if not os.path.exists(os.path.join(repo, p)):
                    bad += 1
    print(f"  {a:6s}: invalid path rate = {bad}/{tot} = {bad/tot:.3f}")

print("\n=== PHASE C/E: repeat 方差 vs entry 间方差 ===")
rsd = []
for e in entries:
    for a in ("agent", "rag", "pack"):
        v = [fr(r) for r in RECS if r["arm"] == a and r["entry_id"] == e]
        if len(v) == 2:
            rsd.append(abs(v[0] - v[1]))
print(f"  repeat-level |diff|: mean={statistics.mean(rsd):.3f} median={statistics.median(rsd):.3f}")
d_ap = paired(entries, "agent", "pack", fr)
d_ar = paired(entries, "agent", "rag", fr)
print(f"  entry-level paired diff SD: agent-pack={statistics.pstdev(d_ap):.3f}  agent-rag={statistics.pstdev(d_ar):.3f}")

print("\n=== PHASE E: CI-width 模拟 ===")
t = {20: 2.093, 40: 2.021, 60: 2.000, 100: 1.984, 140: 1.977, 178: 1.973}
per_entry_cost = 0.065 + 0.057 + 0.057
per_entry_time_s = 72 + 65 + 61
for n in (20, 40, 60, 100, 140, 178):
    hap = round(t[n] * statistics.pstdev(d_ap) / math.sqrt(n), 3)
    har = round(t[n] * statistics.pstdev(d_ar) / math.sqrt(n), 3)
    for r in (2, 3, 5):
        runs = n * 3 * r
        cost = round(n * r * per_entry_cost, 1)
        hours = round(n * r * per_entry_time_s / 3600, 1)
        print(f"  n={n:3d} r={r}: CI半宽 ap={hap:.3f} ar={har:.3f} | runs={runs} cost≈${cost} time≈{hours}h")
