#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
select_samples.py — C-06 micro-MVE 确定性样本选择（STEP 6，预登记规则 v2）

规则冻结于任何模型运行之前（v2 修正 v1 的仓库上限执行缺陷）：
 1. 池：VulnGym v0.1.4 (commit cd69f7e) entries，verify==1。
 2. 分层目标：BL (l1=='业务逻辑') 10（其中 BL-AGENT-CAPABILITY ≥3）+ Traditional 10。
 3. 仓库分散（全局）：**每仓库 ≤1 entry**（最大化覆盖面）。
    - 若某分层因仓库耗尽无法填满，按序放宽至每仓库 ≤2（记录于 selection_log）——分析显示
      10+10 在 1-per-repo 下可实现（BL 17 仓、Trad 15 仓），故该 fallback 预期不触发。
 4. 候选顺序：每分层内按 entry_id 升序（确定性）。
 5. 可及性硬门：blobless clone（600s 超时）+ rev-parse 验证 + 真实 checkout，
    缓存于 05_code/repos/<project>__<commit8>/（幂等）。失败→记录原因，取下一位。
 6. dry_run：未用仓库中的 BL-AGENT-CAPABILITY（预期 AutoGPT）；备件 spare_bl/spare_trad 各 1。
 7. 任务文本冻结：task_title=vuln_title；task_description=GitHub Advisory API description
    （fallback summary），截断 1500 字符 + ' [TRUNCATED]'。一次性抓取写 manifest。
 8. 替换政策：仅允许“基础设施不可行”（clone/checkout/解析失败）且该 entry 尚无任何
    arm 结果时替换；禁止为改善结果替换样本；每次替换记录 selection_log。

输出：06_experiments/c06/sample_manifest.csv + selection_log.md
用法：05_code/venv/bin/python 06_experiments/scripts/c06/select_samples.py
"""

import csv, gzip, io, json, os, subprocess, sys, time, datetime as dt, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VULNGYM = os.path.join(ROOT, "05_code", "VulnGym", "data", "entries.jsonl")
REPOS_DIR = os.path.join(ROOT, "05_code", "repos")
OUT_DIR = os.path.join(ROOT, "06_experiments", "c06")
MANIFEST = os.path.join(OUT_DIR, "sample_manifest.csv")
SELLOG = os.path.join(OUT_DIR, "selection_log.md")
DESC_CAP, CLONE_TIMEOUT = 1500, 600


def sh(cmd, timeout=CLONE_TIMEOUT):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def accessibility_gate(e):
    d = os.path.join(REPOS_DIR, f"{e['project']}__{e['commit'][:8]}")
    if os.path.isdir(os.path.join(d, ".git")):
        r = sh(["git", "-C", d, "rev-parse", "--verify", e["commit"] + "^{commit}"], timeout=60)
        if r.returncode == 0:
            return True, "cached"
    os.makedirs(REPOS_DIR, exist_ok=True)
    r = sh(["git", "clone", "--filter=blob:none", "--no-checkout", e["repo_url"], d])
    if r.returncode != 0:
        return False, f"clone failed: {r.stderr.strip()[:200]}"
    r = sh(["git", "-C", d, "rev-parse", "--verify", e["commit"] + "^{commit}"], timeout=120)
    if r.returncode != 0:
        return False, f"commit missing: {r.stderr.strip()[:120]}"
    r = sh(["git", "-C", d, "checkout", "--detach", e["commit"]], timeout=CLONE_TIMEOUT)
    if r.returncode != 0:
        return False, f"checkout failed: {r.stderr.strip()[:200]}"
    return True, "ok"


def fetch_advisory(report_id, log):
    url = f"https://api.github.com/advisories/{report_id}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "gzip",
                "User-Agent": "c06-mve-selection/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            data = json.loads(raw.decode("utf-8"))
            desc = (data.get("description") or "").strip() or (data.get("summary") or "").strip()
            if not desc:
                return None, "empty"
            if len(desc) > DESC_CAP:
                desc = desc[:DESC_CAP].rstrip() + " [TRUNCATED]"
            return desc, "ok"
        except Exception as ex:  # noqa: BLE001
            log.append(f"    advisory retry {attempt+1} {report_id}: {ex}")
            time.sleep(5 * (attempt + 1))
    return None, "api failed"


def gate_and_fetch(e, log):
    ok, why = accessibility_gate(e)
    if not ok:
        return None, why
    desc, why2 = fetch_advisory(e["report_id"], log)
    if desc is None:
        return None, f"advisory: {why2}"
    return desc, "ok"


def pick(pool, want, used_repos, picked_ids, label, log, cap=1):
    """从 pool（已按 entry_id 排序）按 used_repos 分散选取 want 条（含同一调用内去重）。"""
    got, seen = [], set()
    for e in pool:
        if len(got) >= want:
            break
        if e["entry_id"] in picked_ids or e["repo_url"] in used_repos or e["repo_url"] in seen:
            continue
        desc, why = gate_and_fetch(e, log)
        if desc is None:
            log.append(f"  - EXCLUDE {e['entry_id']} [{label}] {e['project']}: {why}")
            continue
        got.append((e, desc)); seen.add(e["repo_url"])
        log.append(f"  + SELECT {e['entry_id']} [{label}] {e['project']}@{e['commit'][:8]}")
    return got


def main():
    pool = [e for e in (json.loads(l) for l in open(VULNGYM, encoding="utf-8")) if e.get("verify") == 1]
    pool.sort(key=lambda e: e["entry_id"])
    is_bl = lambda e: e.get("vuln_category_l1") == "业务逻辑"
    is_ac = lambda e: "BL-AGENT-CAPABILITY" in (e.get("vuln_category_l2") or "")
    log = ["# C-06 sample selection log (rule v2)",
           "", f"- 执行时间: {dt.datetime.now(dt.timezone.utc).isoformat()}",
           f"- 池: verify==1 → {len(pool)} entries / {len(set(e['repo_url'] for e in pool))} repos",
           "- 规则: 本文件 docstring（v2：全局每仓库 ≤1，修正 v1 repo-cap 执行缺陷；修正发生于任何模型运行之前）", ""]

    picked, used, chosen = set(), set(), []
    ac_pool = [e for e in pool if is_ac(e)]
    bl_pool = [e for e in pool if is_bl(e) and not is_ac(e)]
    trad_pool = [e for e in pool if not is_bl(e)]

    log.append("## 主选择（20 MVE entries）")
    chosen = []
    for label, src, want in (("BL-AGENT-CAPABILITY", ac_pool, 3), ("BL-other", bl_pool, 7), ("Traditional", trad_pool, 10)):
        got = pick(src, want, used, picked, label, log)
        for e, desc in got:
            picked.add(e["entry_id"]); used.add(e["repo_url"])
            chosen.append((e, desc, label))
        if len(got) < want:
            log.append(f"  !! [{label}] 只选到 {len(got)}/{want}（仓库耗尽）")

    mve = list(chosen)
    # fallback：若不足 20，放宽至每仓库 ≤2（记录）
    if len(mve) < 20:
        log.append("## fallback: 放宽至每仓库 ≤2")
        for label, src, want in (("BL-AGENT-CAPABILITY", ac_pool, 3), ("BL-other", bl_pool, 7), ("Traditional", trad_pool, 10)):
            have = sum(1 for _, _, l in mve if l == label)
            need = want - have
            if need <= 0:
                continue
            for e in src:
                if need <= 0:
                    break
                if e["entry_id"] in picked:
                    continue
                cnt = sum(1 for ee, _, _ in mve if ee["repo_url"] == e["repo_url"])
                if cnt >= 2:
                    continue
                desc, why = gate_and_fetch(e, log)
                if desc is None:
                    continue
                picked.add(e["entry_id"]); used.add(e["repo_url"])
                mve.append((e, desc, label)); need -= 1
                log.append(f"  + fallback SELECT {e['entry_id']} [{label}] {e['project']}")

    # dry_run + spares（未用仓库优先）
    log.append("## dry_run 与备件")
    extras = []
    for role, filt in (("dry_run", lambda e: is_ac(e)),
                       ("spare_bl", lambda e: is_bl(e)),
                       ("spare_trad", lambda e: not is_bl(e))):
        for e in pool:
            if e["entry_id"] in picked or e["repo_url"] in used:
                continue
            if not filt(e):
                continue
            desc, why = gate_and_fetch(e, log)
            if desc is None:
                continue
            picked.add(e["entry_id"]); used.add(e["repo_url"])
            extras.append((e, desc, role))
            log.append(f"  + {role}: {e['entry_id']} {e['project']}@{e['commit'][:8]}")
            break

    cols = ["role", "entry_id", "report_id", "project", "repo_url", "commit",
            "vuln_category_l1", "vuln_category_l2", "vuln_title", "task_title", "task_description",
            "ep_file", "ep_line", "co_file", "co_line", "trace_len", "stratum", "selected_at"]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        for e, desc, label in mve:
            w.writerow(["mve", e["entry_id"], e["report_id"], e["project"], e["repo_url"], e["commit"],
                        e.get("vuln_category_l1", ""), e.get("vuln_category_l2", ""),
                        e.get("vuln_title", ""), e.get("vuln_title", ""), desc,
                        e["entry_point"]["file"], e["entry_point"]["line"],
                        e["critical_operation"]["file"], e["critical_operation"]["line"],
                        len(e.get("trace", [])), ("bl" if is_bl(e) else "trad"), now])
        for e, desc, role in extras:
            w.writerow([role, e["entry_id"], e["report_id"], e["project"], e["repo_url"], e["commit"],
                        e.get("vuln_category_l1", ""), e.get("vuln_category_l2", ""),
                        e.get("vuln_title", ""), e.get("vuln_title", ""), desc,
                        e["entry_point"]["file"], e["entry_point"]["line"],
                        e["critical_operation"]["file"], e["critical_operation"]["line"],
                        len(e.get("trace", [])), ("bl" if is_bl(e) else "trad"), now])
    mve_n = len(mve)
    bl_n = sum(1 for e, _, _ in mve if is_bl(e))
    ac_n = sum(1 for e, _, _ in mve if is_ac(e))
    trad_n = mve_n - bl_n
    repos_n = len(set(e["repo_url"] for e, _, _ in mve))
    log += ["", f"## 结果: MVE {mve_n} (BL {bl_n} [agentcap {ac_n}] + TRAD {trad_n})，"
                f"distinct repos {repos_n}，extras {len(extras)}", ""]
    open(SELLOG, "w", encoding="utf-8").write("\n".join(log) + "\n")
    print(f"MVE={mve_n} BL={bl_n} agentcap={ac_n} TRAD={trad_n} repos={repos_n} extras={len(extras)}")
    if mve_n != 20 or bl_n != 10 or trad_n != 10 or ac_n < 3:
        print("WARNING: 目标未完全满足，检查 selection_log")
        sys.exit(1)


if __name__ == "__main__":
    main()
