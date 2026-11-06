#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
select_confirmatory.py — C-06 confirmatory 样本选择（D-011B Step 2，纯确定性，无网络）

冻结规则（先于任何 confirmatory 结果）：
 1. 池：VulnGym v0.1.4 (commit cd69f7e) entries，verify==1（393 / 178 advisories / 23 repos）。
 2. 排除 prior 使用：pilot MVE 20 entry_id、pilot extras（dry_run/spare_*）entry_id、
    以及与之共享 report_id 的全部 entry（同漏洞禁跨 pilot/confirmatory）。
 3. 独立单位 = advisory(report_id)，每 advisory ≤1 entry（多 entry 取 entry_id 最小者）。
 4. 抽样：rng.Random(seed=20260929).shuffle 排序后的 report_id 列表 → 取前 90
    （80 正式 + 10 spares；spares 仅用于补齐 advisory 抓取失败）。
 5. 仓库 cluster：repo_url 规范化（小写去尾斜杠）为 cluster_id。
 6. 不据难度/模型表现调整样本。替换仅因 advisory 不可达（由 annotate 脚本判定）。
 7. task_description / path_hint 由 annotate_confirmatory.py 抓取后回填（先冻结此清单）。

输出：06_experiments/c06/confirmatory_sample_manifest.csv + confirmatory_selection_log.md
"""
import csv
import json
import os
import random
import datetime as dt
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VULNGYM = os.path.join(ROOT, "05_code", "VulnGym", "data", "entries.jsonl")
OUT = os.path.join(ROOT, "06_experiments", "c06")
MANIFEST = os.path.join(OUT, "confirmatory_sample_manifest.csv")
SELLOG = os.path.join(OUT, "confirmatory_selection_log.md")
PILOT_MANIFEST = os.path.join(OUT, "sample_manifest.csv")
SEED, N_TARGET, N_SPARES = 20260929, 80, 10


def canon(u):
    return u.lower().rstrip("/")


def main():
    pool = [e for e in (json.loads(l) for l in open(VULNGYM, encoding="utf-8")) if e.get("verify") == 1]
    pilot_ids, pilot_rids = set(), set()
    for r in csv.DictReader(open(PILOT_MANIFEST, encoding="utf-8")):
        pilot_ids.add(r["entry_id"]); pilot_rids.add(r["report_id"])

    remaining = [e for e in pool if e["entry_id"] not in pilot_ids and e["report_id"] not in pilot_rids]
    adv_best = {}
    for e in remaining:
        if e["report_id"] not in adv_best or e["entry_id"] < adv_best[e["report_id"]]["entry_id"]:
            adv_best[e["report_id"]] = e
    adv_ids = sorted(adv_best.keys())

    rng = random.Random(SEED)
    order = adv_ids[:]
    rng.shuffle(order)
    picked = [(adv_best[rid], rid) for rid in order[: N_TARGET + N_SPARES]]

    cols = ["role", "entry_id", "report_id", "project", "repo_url", "cluster_id", "commit",
            "vuln_category_l1", "vuln_category_l2", "vuln_title", "task_title", "task_description",
            "ep_file", "ep_line", "co_file", "co_line", "trace_len", "stratum", "path_hint", "selected_at"]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        for i, (e, rid) in enumerate(picked):
            role = "confirmatory" if i < N_TARGET else "spare"
            w.writerow([role, e["entry_id"], rid, e["project"], e["repo_url"], canon(e["repo_url"]),
                        e["commit"], e.get("vuln_category_l1", ""), e.get("vuln_category_l2", ""),
                        e.get("vuln_title", ""), e.get("vuln_title", ""), "",
                        e["entry_point"]["file"], e["entry_point"]["line"],
                        e["critical_operation"]["file"], e["critical_operation"]["line"],
                        len(e.get("trace", [])),
                        ("bl" if e.get("vuln_category_l1") == "业务逻辑" else "trad"), "PENDING", now])

    clusters = Counter(canon(e["repo_url"]) for e, _ in picked)
    bl = sum(1 for e, _ in picked if e.get("vuln_category_l1") == "业务逻辑")
    log = ["# C-06 confirmatory sample selection log (frozen, D-011B Step 2)",
           f"- 执行时间: {now}",
           f"- 池: verify==1 {len(pool)}；排除 pilot {len(pilot_ids)} entry / {len(pilot_rids)} report_id 后剩余 {len(remaining)} entries / {len(adv_ids)} advisories",
           f"- seed={SEED}, 正式={N_TARGET}, spares={N_SPARES}, 独立单位=advisory, ≤1 entry/advisory",
           "- 规则: 本文件 docstring（冻结，不据结果修改）", "",
           f"## 抽样结果（前 {N_TARGET} 正式 + {N_SPARES} spare）",
           f"  仓库 clusters: {len(clusters)} 个；top6: {clusters.most_common(6)}",
           f"  BL {bl} / TRAD {N_TARGET + N_SPARES - bl}（含 spare）", ""]
    open(SELLOG, "w", encoding="utf-8").write("\n".join(log) + "\n")
    print(f"frozen: {N_TARGET} confirmatory + {N_SPARES} spares; clusters={len(clusters)}; BL={bl}")
    print("top clusters:", clusters.most_common(8))


if __name__ == "__main__":
    main()
