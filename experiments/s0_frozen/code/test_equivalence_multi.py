#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_equivalence_multi.py — D-013 Phase 2.6：cold-build vs precomputed/cache build 等价性（不调用 LLM）。

覆盖 openclaw（2 commit，触发跨 commit 复用）+ n8n（2 commit）+ langflow（1 commit）。
每仓比较：ordered chunks、chunk hash、embedding shape、数值等价、lexical/vector/fused ranking、
top-k、50k budget 去重/截断、final model-visible repository context SHA256。
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms
import rag_index
import numpy as np

TEST_QUERIES = ["authentication login credentials", "error handling exception",
                "serialization deserialize parse data", "network request response"]


def _tokenize(t):
    return arms._tokenize(t)


def build_cold(repo):
    """原始 cold-build：chunks + 直接 embed（无 cache）。"""
    embedder = arms.FastEmbedder()
    chunks = arms._build_chunks(repo)
    texts = [C.truncate_to_tokens(c["text"], C.EMBED_TRUNC_TOKENS) for c in chunks]
    emb = np.asarray(list(embedder.embed(texts)), dtype="float32")
    return chunks, emb, embedder


def retrieve_and_inject(chunks, emb, embedder, query, budget=50000):
    """复刻 run_arm_rag 的检索 + 50k budget 去重/截断注入。返回注入文本。"""
    from rank_bm25 import BM25Okapi
    bm25 = BM25Okapi([_tokenize(c["text"]) for c in chunks])
    q = _tokenize(query)
    scores = bm25.get_scores(q)
    bm_rank = sorted(range(len(chunks)), key=lambda i: -scores[i])
    qv = np.asarray(list(embedder.embed([query]))[0], dtype="float32").ravel()
    ev = np.asarray(emb, dtype="float32")
    cos = (ev @ qv) / (np.linalg.norm(ev, axis=1) * (np.linalg.norm(qv) + 1e-9) + 1e-9)
    emb_rank = sorted(range(len(chunks)), key=lambda i: -cos[i])
    score = {}
    for r, i in enumerate(bm_rank):
        score[i] = score.get(i, 0.0) + 1.0 / (C.RRF_K + r + 1)
    for r, i in enumerate(emb_rank):
        score[i] = score.get(i, 0.0) + 1.0 / (C.RRF_K + r + 1)
    order = sorted(score, key=lambda i: -score[i])
    ledger = C.Ledger()
    seen = set()
    parts = []
    for idx in order:
        if ledger.remaining() <= 0:
            break
        key = (chunks[idx]["path"], chunks[idx]["start"])
        if key in seen:
            continue
        seen.add(key)
        text = f"{chunks[idx]['path']}:{chunks[idx]['start']}-{chunks[idx]['end']}\n" + chunks[idx]["text"]
        counted = ledger.add_repo_block(chunks[idx]["path"], text, "rag", cap=ledger.remaining())
        parts.append(counted)
    return order, "\n\n".join(parts)


def check_repo(project, repo_url, commit, embedder_shared, label):
    """cold vs precomputed 等价性检查。"""
    import subprocess
    d = os.path.join(C.ROOT, "05_code", "repos", f"{project}__{commit[:8]}")
    if not os.path.isdir(d):
        return {"label": label, "ok": False, "detail": f"checkout 缺失 {d}"}

    # precomputed（cache path）
    chunks_pc, emb_pc, meta = rag_index.load_index_integrity(project, commit)
    # cold path（用共享 embedder 重新构建）
    t0 = __import__("time").time()
    chunks_cold, emb_cold, _ = build_cold(d)
    cold_secs = __import__("time").time() - t0

    res = {"label": label, "cold_seconds": round(cold_secs, 1), "num_chunks": len(chunks_pc)}
    # 1. ordered chunks 一致
    res["chunks_identical"] = chunks_pc == chunks_cold
    # 2. chunk 文本 hash 一致
    hpc = hashlib.sha256(json.dumps(chunks_pc, ensure_ascii=False).encode()).hexdigest()
    hcold = hashlib.sha256(json.dumps(chunks_cold, ensure_ascii=False).encode()).hexdigest()
    res["chunks_hash_identical"] = hpc == hcold
    # 3. embedding shape
    res["emb_shape_identical"] = emb_pc.shape == emb_cold.shape
    # 4. 数值等价
    if emb_pc.shape == emb_cold.shape:
        maxdiff = float(np.max(np.abs(emb_pc.astype("float64") - emb_cold.astype("float64")))) if len(emb_pc) else 0.0
        res["emb_byte_identical"] = bool(np.array_equal(emb_pc, emb_cold))
        res["max_abs_diff"] = maxdiff
    # 5-6. ranking + injected context（用共享 embedder 一致性；用 cold embedder 与 pc embedder 各自检索）
    emb_cold_embedder = arms.FastEmbedder()
    ranking_ok = inj_ok = True
    for q in TEST_QUERIES:
        o_pc, inj_pc = retrieve_and_inject(chunks_pc, emb_pc, emb_cold_embedder, q)
        o_cold, inj_cold = retrieve_and_inject(chunks_cold, emb_cold, emb_cold_embedder, q)
        if o_pc[:50] != o_cold[:50]:
            ranking_ok = False
        if hashlib.sha256(inj_pc.encode()).hexdigest() != hashlib.sha256(inj_cold.encode()).hexdigest():
            inj_ok = False
    res["ranking_identical"] = ranking_ok
    res["injected_context_sha256_identical"] = inj_ok
    res["ok"] = (res["chunks_identical"] and res["chunks_hash_identical"]
                 and res["emb_shape_identical"] and res["ranking_identical"] and inj_ok)
    return res


def main():
    import csv
    rows = [r for r in csv.DictReader(open(os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_sample_manifest.csv")))
            if r["role"] in ("confirmatory", "spare")]
    # 选择：openclaw 2 commit（含跨 commit 复用）、n8n 2 commit、langflow 1 commit
    def picks(cluster_keyword, n):
        by_commit = {}
        for r in rows:
            if cluster_keyword in r["cluster_id"]:
                by_commit.setdefault(r["commit"], r)
        chosen = list(by_commit.values())[:n]
        return chosen
    openclaw = picks("openclaw", 2)
    n8n = picks("n8n-io/n8n", 2)
    langflow = picks("langflow-ai/langflow", 1)
    targets = langflow + openclaw + n8n  # 小的先跑，快速验证逻辑

    print("=== 等价性目标 ===")
    for r in targets:
        hits = "?"
        meta_file = os.path.join(rag_index._index_dir(r["project"], r["commit"]), "index_meta.json")
        if os.path.exists(meta_file):
            m = json.load(open(meta_file))
            hits = f"hits={m['chunk_cache']['hits']} misses={m['chunk_cache']['misses']}"
        print(f"  {r['project']}@{r['commit'][:8]} ({r['cluster_id'].split('/')[-1]}) {hits}")

    results = []
    for r in targets:
        label = f"{r['cluster_id'].split('/')[-1]}@{r['commit'][:8]}"
        print(f"\n检查 {label} ...", flush=True)
        res = check_repo(r["project"], r["repo_url"], r["commit"], None, label)
        results.append(res)
        for k, v in res.items():
            if k not in ("label", "ok"):
                print(f"    {k}={v}")
        print(f"    -> {'OK' if res['ok'] else 'FAIL'}")

    allpass = all(r["ok"] for r in results)
    has_cross_commit = any(json.load(open(os.path.join(rag_index._index_dir(r["project"], r["commit"]), "index_meta.json")))["chunk_cache"]["hits"] > 0
                           for r in openclaw + n8n)
    print(f"\n跨 commit 复用已触发（openclaw/n8n 至少一 commit hits>0）: {has_cross_commit}")
    print(f"COLD/CACHED EQUIVALENCE: {'PASS' if (allpass and has_cross_commit) else 'FAIL'}")
    out = os.path.join(C.ROOT, "06_experiments", "c06", "equivalence_multi_test.json")
    json.dump({"all_pass": allpass and has_cross_commit, "results": results}, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    sys.exit(0 if (allpass and has_cross_commit) else 1)


if __name__ == "__main__":
    main()
