#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annotate_confirmatory.py — D-011B Step 3：抓取 90 条 confirmatory/spare 的 advisory 描述，
回填 task_description + PATH_HINT 注解（冻结规则 R1/R2）。

限流感知：HTTP 403/429 视为基础设施限流（非 advisory 不可用），按 Retry-After 或
指数退避等待后重试，最多 8 次；仅最终失败才标记 FETCH_FAILED（由 spare 补齐）。
进度逐条 flush 输出。
"""
import csv
import gzip
import io
import json
import os
import re
import time
import datetime as dt
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(ROOT, "06_experiments", "c06")
MANIFEST = os.path.join(OUT, "confirmatory_sample_manifest.csv")
FETCHLOG = os.path.join(OUT, "confirmatory_advisory_fetch.log")
DESC_CAP = 1500

R1 = re.compile(r"/[\w\-./]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql|css|html)", re.I)
R2 = re.compile(r"\b[\w\-]+\.(py|js|ts|jsx|tsx|vue|svelte|go|java|rb|php|c|h|cpp|rs|sh|sql)\b", re.I)


def fetch(rid, log, max_err_attempts=5):
    url = f"https://api.github.com/advisories/{rid}"
    err_attempt = 0
    while True:  # 限流循环：等 reset 后重试，不算失败
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github+json", "Accept-Encoding": "gzip",
                "User-Agent": "c06-confirmatory-annotate/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            data = json.loads(raw.decode("utf-8"))
            desc = (data.get("description") or "").strip() or (data.get("summary") or "").strip()
            if not desc:
                return None
            return desc[:DESC_CAP].rstrip() + (" [TRUNCATED]" if len(desc) > DESC_CAP else "")
        except urllib.error.HTTPError as ex:
            if ex.code in (403, 429):
                reset = ex.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = max(0, int(reset) - time.time()) + 2
                else:
                    wait = int(ex.headers.get("Retry-After", 60)) + 2
                wait = min(wait, 3600)
                log.append(f"  rate-limit {rid} HTTP {ex.code}: wait {int(wait)}s")
                print(f"rate-limit {rid} HTTP {ex.code}: wait {int(wait)}s", flush=True)
                time.sleep(wait)
                continue  # 限流不耗尽错误尝试
            log.append(f"  HTTP {ex.code} {rid}: {ex.reason}")
            return None  # 404 等真实不可用
        except Exception as ex:  # noqa: BLE001
            err_attempt += 1
            log.append(f"  err {rid} attempt {err_attempt}: {ex}")
            if err_attempt >= max_err_attempts:
                return None
            time.sleep(10)
    return None


def main():
    rows = list(csv.DictReader(open(MANIFEST, encoding="utf-8")))
    cols = list(rows[0].keys())
    log = [f"# confirmatory advisory fetch log (resume) — {dt.datetime.now(dt.timezone.utc).isoformat()}"]
    todo = [r for r in rows if r["path_hint"] == "PENDING" or not r["task_description"].strip()]
    print(f"fetching {len(todo)} remaining advisories...", flush=True)
    ok = fail = 0
    for i, r in enumerate(todo):
        desc = fetch(r["report_id"], log)
        if desc is None:
            r["task_description"] = ""
            r["path_hint"] = "FETCH_FAILED"
            fail += 1
            print(f"[{i+1}/{len(todo)}] {r['entry_id']} {r['report_id']}: FAILED", flush=True)
        else:
            d = desc.lower()
            r["task_description"] = desc
            r["path_hint"] = "PATH_HINT" if (R1.search(d) or R2.search(d)) else "NO_PATH_HINT"
            ok += 1
            print(f"[{i+1}/{len(todo)}] {r['entry_id']} {r['report_id']}: {r['path_hint']}", flush=True)
        # 增量写回（断点续传友好）
        with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_ALL)
            w.writeheader(); w.writerows(rows)
        time.sleep(1.0)

    log.append(f"# done: ok={ok} failed={fail}")
    open(FETCHLOG, "w", encoding="utf-8").write("\n".join(log) + "\n")
    print(f"DONE ok={ok} failed={fail}", flush=True)


if __name__ == "__main__":
    main()
