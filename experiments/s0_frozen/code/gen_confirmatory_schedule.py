#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_confirmatory_schedule.py — C-06 confirmatory 调度生成（冻结，D-011B）。

规则（冻结，先于任何 confirmatory 结果）：
 - 80 confirmatory entries × 3 arms × 3 repeats = 720 cells。
 - entry-blocked：每个 (entry, repeat) 内三臂按确定随机序排列（position 0/1/2）。
 - 随机源：random.Random(f"{SEED}|{entry_id}|{repeat}")（字符串种子，跨进程确定性，非 Python hash()）。
 - 全局 SEED = 20260928。
"""
import csv
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MAN = os.path.join(ROOT, "06_experiments", "c06", "confirmatory_sample_manifest.csv")
OUT = os.path.join(ROOT, "06_experiments", "c06", "confirmatory_run_schedule.csv")
SEED = 20260928
ARMS = ["agent", "rag", "pack"]
REPEATS = 3


def main():
    rows = [r for r in csv.DictReader(open(MAN, encoding="utf-8")) if r["role"] == "confirmatory"]
    entries = sorted(r["entry_id"] for r in rows)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_id", "repeat", "position", "arm", "seed"])
        for e in entries:
            for rep in range(1, REPEATS + 1):
                rng = random.Random(f"{SEED}|{e}|{rep}")
                order = ARMS[:]
                rng.shuffle(order)
                for pos, arm in enumerate(order):
                    w.writerow([e, rep, pos, arm, SEED])
    n = len(entries) * len(ARMS) * REPEATS
    print(f"schedule written: {len(entries)} entries × {len(ARMS)} arms × {REPEATS} repeats = {n} cells")
    assert n == 720, n


if __name__ == "__main__":
    main()
