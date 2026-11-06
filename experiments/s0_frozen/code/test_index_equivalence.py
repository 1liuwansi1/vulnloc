#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_index_equivalence.py — D-013 STEP 4：证明 cold-build 与 content-addressed cache build 等价。

不调用 LLM、不接触 confirmatory ground truth、不看 accuracy。
用 development-only repo（onnx，非 confirmatory）。

验证：
 1. chunks 一致（arms._build_chunks == rag_index.build_chunks_and_manifest）。
 2. embedding byte-identical（cold 直接 embed vs 空缓存 cache build）。
 3. cache 复用 byte-identical（warm cache 二次 build == cold）。
 4. 检索等价：固定 query 下 BM25/embedding/fused 排名、top-k chunk ID、注入文本、注入文本 SHA256。
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms
import rag_index
import numpy as np

ROOT = C.ROOT
DEV_REPO_DIR = os.path.join(ROOT, "05_code", "repos", "typescript-sdk__50d9fa3c")
DEV_REPO_URL = "https://github.com/modelcontextprotocol/typescript-sdk"
DEV_COMMIT = "bca0315ff3e5"  # 实际 commit 由 repo 目录解析
TEST_QUERIES = [
    "error handling exception message",
    "authentication login credentials",
    "serialization deserialize parse data",
    "network request response client",
]


def _tokenize(text):
    return arms._tokenize(text)


def retrieve(chunks, emb, embedder, query):
    """复刻 arms.run_arm_rag 的检索逻辑（BM25 + BGE cosine + RRF 融合）。"""
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
    return bm_rank, emb_rank, order


def build_cold(repo, embedder):
    """原始 cold-build 路径（arms._build_chunks + 直接 embed）。"""
    chunks = arms._build_chunks(repo)
    texts = [C.truncate_to_tokens(c["text"], C.EMBED_TRUNC_TOKENS) for c in chunks]
    emb = np.asarray(list(embedder.embed(texts)), dtype="float32")
    return chunks, emb


def main():
    checks = []
    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    repo = DEV_REPO_DIR
    # 解析真实 commit
    import subprocess
    commit = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"dev repo: onnx @ {commit[:12]}")

    embedder = arms.FastEmbedder()
    print("embedder loaded", flush=True)

    # 隔离缓存目录（临时）
    tmp = tempfile.mkdtemp(prefix="c06_equiv_")
    rag_index.CHUNK_EMB_CACHE_DIR = os.path.join(tmp, "chunk_cache")
    rag_index.INDEX_CACHE_DIR = os.path.join(tmp, "index_cache")

    # 1. chunks 一致
    print("step1: build cold...", flush=True)
    chunks_cold, emb_cold = build_cold(repo, embedder)
    print(f"  cold: {len(chunks_cold)} chunks, emb shape {emb_cold.shape}", flush=True)
    chunks_new, manifest = rag_index.build_chunks_and_manifest(repo)
    chunks_same = (chunks_cold == chunks_new)
    check("chunks 一致 (arms vs rag_index)", chunks_same,
          f"n_cold={len(chunks_cold)} n_new={len(chunks_new)}")
    if not chunks_same:
        # 找第一处差异
        for i, (a, b) in enumerate(zip(chunks_cold, chunks_new)):
            if a != b:
                check("chunks 首处差异", False, f"index {i}")
                break
        check("chunks 长度一致", len(chunks_cold) == len(chunks_new))

    # 2. 空缓存 cache build vs cold（byte-identical）
    print("step2: precompute (empty cache)...", flush=True)
    meta, icdir = rag_index.precompute_index("typescript-sdk", DEV_REPO_URL, commit, repo, embedder)
    print(f"  precompute: {meta['num_chunks']} chunks, hits={meta['chunk_cache']['hits']} misses={meta['chunk_cache']['misses']}", flush=True)
    chunks_pc = json.load(open(os.path.join(icdir, "chunks.json"), encoding="utf-8"))
    emb_pc = np.load(os.path.join(icdir, "emb.npy"))
    byte_id = np.array_equal(emb_cold, emb_pc)
    maxdiff = float(np.max(np.abs(emb_cold.astype("float64") - emb_pc.astype("float64")))) if len(emb_cold) else 0.0
    check("embedding byte-identical (cold vs 空缓存)", byte_id, f"max_abs_diff={maxdiff:.3e}")
    check("chunks 与 precompute 输出一致", [c["path"] for c in chunks_pc] == [c["path"] for c in chunks_cold])

    # 3. warm 缓存二次 build（全 hit）== cold
    print("step3: precompute (warm cache)...", flush=True)
    meta2, icdir2 = rag_index.precompute_index("typescript-sdk", DEV_REPO_URL, commit, repo, embedder)
    print(f"  warm: hits={meta2['chunk_cache']['hits']} misses={meta2['chunk_cache']['misses']}", flush=True)
    emb_warm = np.load(os.path.join(icdir2, "emb.npy"))
    reuse_id = np.array_equal(emb_cold, emb_warm)
    check("cache 复用 byte-identical (warm == cold)", reuse_id)
    check("二次 build 全 cache hit", meta2["chunk_cache"]["misses"] == 0,
          f"hits={meta2['chunk_cache']['hits']} misses={meta2['chunk_cache']['misses']}")

    # 4. 检索等价（固定 query）
    retrieval_same = True
    for q in TEST_QUERIES:
        bm1, e1, o1 = retrieve(chunks_cold, emb_cold, embedder, q)
        bm2, e2, o2 = retrieve(chunks_pc, emb_pc, embedder, q)
        same = (bm1[:50] == bm2[:50]) and (e1[:50] == e2[:50]) and (o1[:50] == o2[:50])
        retrieval_same &= same
        if not same:
            check(f"检索等价 query='{q[:20]}'", False, "top50 排名不同")
    check("检索等价（4 固定 query，BM25/embedding/fused top50）", retrieval_same)

    # 5. 注入文本 SHA256（top-10 fused 注入）
    inj_same = True
    for q in TEST_QUERIES:
        _, _, o1 = retrieve(chunks_cold, emb_cold, embedder, q)
        _, _, o2 = retrieve(chunks_pc, emb_pc, embedder, q)
        for k in (5, 10):
            t1 = "\n\n".join(f"{chunks_cold[i]['path']}:{chunks_cold[i]['start']}-{chunks_cold[i]['end']}\n{chunks_cold[i]['text']}" for i in o1[:k])
            t2 = "\n\n".join(f"{chunks_pc[i]['path']}:{chunks_pc[i]['start']}-{chunks_pc[i]['end']}\n{chunks_pc[i]['text']}" for i in o2[:k])
            if hashlib.sha256(t1.encode()).hexdigest() != hashlib.sha256(t2.encode()).hexdigest():
                inj_same = False
                check(f"注入文本 SHA256 query='{q[:15]}' top{k}", False)
    check("注入文本 SHA256 一致", inj_same)

    allpass = all(ok for _, ok, _ in checks)
    print("\n=== 等价性结果 ===")
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
    print(f"\nEQUIVALENCE: {'PASS' if allpass else 'FAIL'}")
    # 输出结果 JSON
    out = os.path.join(C.ROOT, "06_experiments", "c06", "index_equivalence_test.json")
    json.dump({"all_pass": allpass, "checks": [{"name": n, "pass": o, "detail": d} for n, o, d in checks],
               "dev_repo": {"url": DEV_REPO_URL, "commit": commit, "n_chunks": len(chunks_cold)},
               "max_abs_diff": float(maxdiff) if len(emb_cold) else 0.0},
              open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print("written:", os.path.relpath(out, ROOT))
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
