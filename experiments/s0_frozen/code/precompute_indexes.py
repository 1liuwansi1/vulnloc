#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
precompute_indexes.py — D-013 STEP 6：为全部 frozen confirmatory + spare entries 离线预计算 RAG indexes。

不调用 LLM、不看 accuracy、不改 scientific treatment。
 - 去重 unit = (project, commit)（与 runner 的 index 查找一致）。
 - 每 unit：checkout（blobless clone/复用缓存）+ rag_index.precompute_index（content-addressed 去重）。
 - 幂等：已存在 index_meta.json 的跳过（可断点续跑）。
 - 全局统计：总 index 数、唯一 repo/commit、总 chunks、唯一 chunk hash（embedding cache 文件数）、
   全局 cache 命中率、总墙钟、CPU 时间。
"""
import csv
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms
import rag_index

MANIFEST = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_sample_manifest.csv")
REPOS_DIR = os.path.join(C.ROOT, "05_code", "repos")
PROGRESS_LOG = os.path.join(C.ROOT, "06_experiments", "c06", "precompute_progress.log")
CLONE_TIMEOUT = 600


def checkout(project, repo_url, commit, log):
    d = os.path.join(REPOS_DIR, f"{project}__{commit[:8]}")
    if os.path.isdir(os.path.join(d, ".git")):
        r = subprocess.run(["git", "-C", d, "rev-parse", "--verify", commit + "^{commit}"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            r2 = subprocess.run(["git", "-C", d, "checkout", "--detach", commit],
                                capture_output=True, text=True, timeout=CLONE_TIMEOUT)
            return d, (r2.returncode == 0)
    os.makedirs(REPOS_DIR, exist_ok=True)
    r = subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", repo_url, d],
                       capture_output=True, text=True, timeout=CLONE_TIMEOUT)
    if r.returncode != 0:
        log.append(f"  clone failed {project} {commit[:8]}: {r.stderr.strip()[:200]}")
        return None, False
    r = subprocess.run(["git", "-C", d, "checkout", "--detach", commit],
                       capture_output=True, text=True, timeout=CLONE_TIMEOUT)
    if r.returncode != 0:
        log.append(f"  checkout failed {project} {commit[:8]}: {r.stderr.strip()[:200]}")
        return None, False
    return d, True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rows = [r for r in csv.DictReader(open(MANIFEST, encoding="utf-8"))
            if r["role"] in ("confirmatory", "spare")]
    units = {}
    for r in rows:
        key = (r["project"], r["commit"], r["repo_url"])
        units[key] = r
    units = dict(sorted(units.items()))
    if args.limit:
        units = dict(list(units.items())[:args.limit])
    log = [f"# precompute started {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
           f"# distinct (project,commit) units: {len(units)}"]
    print(f"precompute units: {len(units)}", flush=True)

    embedder = arms.FastEmbedder()
    print("embedder loaded", flush=True)

    t_start = time.time()
    done = skip = fail = 0
    total_chunks = 0
    global_hits = global_misses = 0
    for i, (key, r) in enumerate(sorted(units.items())):
        project, commit, repo_url = key
        # 跳过已构建
        from rag_index import _index_dir
        if os.path.exists(os.path.join(_index_dir(project, commit), "index_meta.json")):
            skip += 1
            print(f"[{i+1}/{len(units)}] SKIP(exists) {project}@{commit[:8]}", flush=True)
            continue
        d, ok = checkout(project, repo_url, commit, log)
        if not ok:
            fail += 1
            log.append(f"  FAIL checkout {project}@{commit[:8]}")
            print(f"[{i+1}/{len(units)}] FAIL checkout {project}@{commit[:8]}", flush=True)
            continue
        try:
            meta, icdir = rag_index.precompute_index(project, repo_url, commit, d, embedder)
            done += 1
            total_chunks += meta["num_chunks"]
            global_hits += meta["chunk_cache"]["hits"]
            global_misses += meta["chunk_cache"]["misses"]
            print(f"[{i+1}/{len(units)}] OK {project}@{commit[:8]} chunks={meta['num_chunks']} "
                  f"hits={meta['chunk_cache']['hits']} misses={meta['chunk_cache']['misses']} "
                  f"t={meta['timing']['total']}s", flush=True)
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.append(f"  FAIL precompute {project}@{commit[:8]}: {str(e)[:200]}")
            print(f"[{i+1}/{len(units)}] FAIL {project}@{commit[:8]}: {str(e)[:150]}", flush=True)

    wall = time.time() - t_start
    # 唯一 chunk hash = embedding cache 文件数
    emb_cache_dir = os.path.join(rag_index.CHUNK_EMB_CACHE_DIR, rag_index.embedding_config_hash()[:16])
    unique_chunks = len(os.listdir(emb_cache_dir)) if os.path.isdir(emb_cache_dir) else 0
    # CPU time
    import resource
    cpu = resource.getrusage(resource.RUSAGE_SELF)
    summary = {
        "done": done, "skipped": skip, "failed": fail,
        "total_indexes": done + skip, "units": len(units),
        "total_chunks": total_chunks,
        "unique_chunk_hashes": unique_chunks,
        "global_cache_hits": global_hits, "global_cache_misses": global_misses,
        "global_hit_rate": round(global_hits / max(1, global_hits + global_misses), 4),
        "wall_seconds": round(wall, 1),
        "cpu_user_seconds": round(cpu.ru_utime, 1),
        "cpu_sys_seconds": round(cpu.ru_stime, 1),
        "finished_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    log.append("# summary: " + json.dumps(summary))
    open(PROGRESS_LOG, "w", encoding="utf-8").write("\n".join(log) + "\n")
    json.dump(summary, open(os.path.join(C.ROOT, "06_experiments", "c06", "precompute_summary.json"),
                            "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("\n=== PRECOMPUTE SUMMARY ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
