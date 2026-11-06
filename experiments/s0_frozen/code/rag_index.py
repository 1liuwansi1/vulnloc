#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rag_index.py — D-013 RAG index infrastructure revision.

把 RAG indexing 从在线 run 拆成任务盲 offline preprocessing，并加 content-addressed
chunk embedding cache（消除跨 commit 重复 embedding）。

关键不变量（不改变任何 scientific treatment）：
  - chunking 逻辑与 arms.py 原 _build_chunks 完全一致（60 行/45 步长/40k cap）。
  - embedding 输入 = truncate_to_tokens(chunk.text, EMBED_TRUNC_TOKENS)（与在线一致）。
  - 检索算法（BM25 + BGE + RRF）不变；本模块只负责 index 的构建/加载/校验。

模块结构：
  - embedding_config_fingerprint() / embedding_config_hash()
  - build_chunks_and_manifest(repo)  (chunks + 每源文件 sha256)
  - index_config_hash(repo_url, commit, manifest)
  - ChunkEmbeddingCache  (content-addressed: sha256(embed_input + emb_config_hash))
  - precompute_index(...)  (构建 + 缓存嵌入 + 写 index + metadata)
  - load_index_integrity(...)  (加载 + 校验，缺失/不匹配 → 抛异常 STOP)
"""
import hashlib
import json
import os
import time

import common as C

CHUNKING_VERSION = "c06-v1"
EMBED_MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_SNAPSHOT = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
EMBED_ONNX_SHA256 = "51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431"
EMBED_TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"
EMBED_DIM = 384

INDEX_CACHE_DIR = os.path.join(C.ROOT, "05_code", "index_cache")
CHUNK_EMB_CACHE_DIR = os.path.join(C.ROOT, "05_code", "embedding_cache")


class IndexIntegrityError(RuntimeError):
    """预计算 index 完整性失败（缺失/哈希不匹配/config 不匹配）。必须 fail-closed 停止整个实验。"""


def _runtime_versions():
    import fastembed
    import onnxruntime
    import numpy
    return {"fastembed": fastembed.__version__, "onnxruntime": onnxruntime.__version__,
            "numpy": numpy.__version__}


def embedding_config_fingerprint():
    """embedding pipeline 的完整配置指纹（dict + 规范化 json）。"""
    v = _runtime_versions()
    cfg = {
        "model_id": EMBED_MODEL_ID,
        "model_snapshot": EMBED_MODEL_SNAPSHOT,
        "onnx_sha256": EMBED_ONNX_SHA256,
        "tokenizer_sha256": EMBED_TOKENIZER_SHA256,
        "dim": EMBED_DIM,
        "fastembed": v["fastembed"],
        "onnxruntime": v["onnxruntime"],
        "numpy": v["numpy"],
        "embed_trunc_tokens": C.EMBED_TRUNC_TOKENS,
        "execution": "onnxruntime-cpu-default",
    }
    return cfg


def embedding_config_hash():
    cfg = embedding_config_fingerprint()
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()


def chunk_embedding_cache_key(embed_input_text):
    """content-addressed key = sha256(embed_input_bytes + embedding_config_hash)。"""
    return hashlib.sha256(embed_input_text.encode("utf-8") + embedding_config_hash().encode("utf-8")).hexdigest()


def build_chunks_and_manifest(repo):
    """确定性 chunking + 源文件 manifest（每源文件 sha256）。与 arms.py 原逻辑一致。

    返回 (chunks, manifest)，manifest = [{"path","sha256","size"}]（按源文件遍历序）。
    """
    chunks = []
    manifest = []
    for rel in C.iter_source_files(repo):
        content = C.read_text(repo, rel)
        if content is None:
            continue
        full = os.path.join(repo, rel)
        size = os.path.getsize(full)
        manifest.append({"path": rel, "size": size,
                         "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
        if len(chunks) >= C.CHUNK_CAP:
            continue
        lines = content.splitlines()
        step = max(1, C.CHUNK_LINES - C.CHUNK_OVERLAP)
        for s in range(0, len(lines), step):
            if len(chunks) >= C.CHUNK_CAP:
                break
            seg = lines[s:s + C.CHUNK_LINES]
            if any(x.strip() for x in seg):
                chunks.append({"path": rel, "start": s + 1, "end": s + len(seg),
                               "text": "\n".join(seg)})
    return chunks, manifest


def index_config_hash(repo_url, commit, manifest):
    """完整 index 配置指纹：仓库+commit+源文件清单+每文件 sha256+chunking 政策+embedding 配置。"""
    src_policy = {
        "source_exts": sorted(C.SOURCE_EXTS),
        "skip_ext": sorted(C.SKIP_EXT),
        "skip_filenames": sorted(C.SKIP_FILENAMES),
        "binary_hints": [h.hex() if isinstance(h, bytes) else str(h) for h in C.BINARY_HINTS],
        "max_file_bytes": C.MAX_FILE_BYTES,
        "ordering": "os.walk(sorted dirs, sorted files) + final sorted",
    }
    cfg = {
        "repo_url": repo_url.lower().rstrip("/"),
        "commit": commit,
        "chunking_version": CHUNKING_VERSION,
        "chunk_lines": C.CHUNK_LINES,
        "chunk_overlap": C.CHUNK_OVERLAP,
        "chunk_cap": C.CHUNK_CAP,
        "embed_trunc_tokens": C.EMBED_TRUNC_TOKENS,
        "accounting_tokenizer": "cl100k_base",
        "embedding": embedding_config_fingerprint(),
        "source_policy": src_policy,
        "file_manifest": manifest,  # [{path,size,sha256}]
    }
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()


def _index_dir(project, commit):
    return os.path.join(INDEX_CACHE_DIR, f"{project}__{commit[:8]}__{embedding_config_hash()[:12]}")


class ChunkEmbeddingCache:
    """content-addressed chunk embedding cache（只对逐字节相同 + 配置相同的 chunk 复用）。"""

    def __init__(self):
        self.dir = os.path.join(CHUNK_EMB_CACHE_DIR, embedding_config_hash()[:16])
        os.makedirs(self.dir, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def path(self, key):
        return os.path.join(self.dir, key + ".npy")

    def get(self, key):
        p = self.path(key)
        if os.path.exists(p):
            import numpy as np
            self.hits += 1
            return np.load(p)
        return None

    def put(self, key, emb):
        import numpy as np
        np.save(self.path(key), np.asarray(emb, dtype="float32"))
        self.misses += 1


def embed_input_text(chunk):
    """与在线路径完全一致的 embedding 输入（truncate 到 EMBED_TRUNC_TOKENS cl100k tokens）。"""
    return C.truncate_to_tokens(chunk["text"], C.EMBED_TRUNC_TOKENS)


def precompute_index(project, repo_url, commit, repo, embedder):
    """离线预计算一个 (repo, commit) 的 RAG index（用 content-addressed cache 去重）。

    返回 metadata dict（含各阶段耗时 + cache 命中率）。
    """
    import numpy as np
    t0 = time.time()
    t_scan = t_chunk = t_embed = t_write = 0.0

    t = time.time()
    chunks, manifest = build_chunks_and_manifest(repo)
    t_chunk = time.time() - t

    cfg_hash = index_config_hash(repo_url, commit, manifest)
    icdir = _index_dir(project, commit)
    os.makedirs(icdir, exist_ok=True)

    cache = ChunkEmbeddingCache()
    t = time.time()
    keys = [chunk_embedding_cache_key(embed_input_text(c)) for c in chunks]
    emb = np.zeros((len(chunks), EMBED_DIM), dtype="float32")
    miss_idx = []
    for i, k in enumerate(keys):
        v = cache.get(k)
        if v is not None:
            emb[i] = v
        else:
            miss_idx.append(i)
    if miss_idx:
        texts = [embed_input_text(chunks[i]) for i in miss_idx]
        vecs = np.asarray(list(embedder.embed(texts)), dtype="float32")
        for j, i in enumerate(miss_idx):
            emb[i] = vecs[j]
            cache.put(keys[i], vecs[j])
    t_embed = time.time() - t

    t = time.time()
    chunks_out = [{"path": c["path"], "start": c["start"], "end": c["end"], "text": c["text"]} for c in chunks]
    with open(os.path.join(icdir, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(chunks_out, f, ensure_ascii=False)
    np.save(os.path.join(icdir, "emb.npy"), emb)
    t_write = time.time() - t

    # 写 metadata（含 hash，供完整性校验）
    chunks_bytes = json.dumps(chunks_out, ensure_ascii=False).encode("utf-8")
    meta = {
        "project": project, "repo_url": repo_url, "commit": commit,
        "index_config_hash": cfg_hash,
        "embedding_config_hash": embedding_config_hash(),
        "chunks_sha256": hashlib.sha256(chunks_bytes).hexdigest(),
        "emb_sha256": hashlib.sha256(emb.tobytes()).hexdigest(),
        "num_chunks": len(chunks),
        "num_source_files": len(manifest),
        "dim": EMBED_DIM,
        "chunk_cache": {"hits": cache.hits, "misses": cache.misses,
                        "hit_rate": round(cache.hits / max(1, cache.hits + cache.misses), 4)},
        "timing": {"scan_chunk": round(t_chunk, 2), "embed": round(t_embed, 2),
                   "write": round(t_write, 2), "total": round(time.time() - t0, 2)},
        "built_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "environment": {"fastembed": _runtime_versions()["fastembed"],
                        "onnxruntime": _runtime_versions()["onnxruntime"],
                        "numpy": _runtime_versions()["numpy"]},
    }
    with open(os.path.join(icdir, "index_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta, icdir


def load_index_integrity(project, commit):
    """加载预计算 index 并校验完整性 + 绑定冻结 manifest（D-013 re-audit Phase 3+4）。

    所有加载/身份验证阶段的异常（corrupt .npy、numpy load 错误、malformed metadata、
    缺失字段、shape/dtype 错误、哈希读取失败、意外 loader 异常）→ IndexIntegrityError
    （INFRASTRUCTURE_ERROR，全局 STOP，不 arm-level retry，不继续 schedule）。
    绑定 confirmatory_index_manifest.json：repo/commit/index_config_hash/embedding 指纹/
    chunks/emb SHA256/count/row count/dim 必须与冻结 manifest entry 一致，禁止 silent fallback/rebuild。
    """
    import numpy as np
    icdir = _index_dir(project, commit)
    chunks_file = os.path.join(icdir, "chunks.json")
    emb_file = os.path.join(icdir, "emb.npy")
    meta_file = os.path.join(icdir, "index_meta.json")

    # 缺失 → STOP
    if not (os.path.exists(chunks_file) and os.path.exists(emb_file) and os.path.exists(meta_file)):
        raise IndexIntegrityError(f"[rag_index] 预计算 index 缺失: {icdir}（STOP）")

    # 所有后续读取/解析都包在 catch-all 里
    try:
        meta = json.load(open(meta_file, encoding="utf-8"))
        if not isinstance(meta, dict):
            raise ValueError("index_meta.json 非 dict")
        chunks_bytes = open(chunks_file, "rb").read()
        emb = np.load(emb_file, allow_pickle=False)
    except IndexIntegrityError:
        raise
    except Exception as e:  # noqa: BLE001
        raise IndexIntegrityError(f"[rag_index] index 加载失败: {icdir}: {str(e)[:200]}（STOP）") from e

    # dtype 校验
    if emb.dtype != np.float32:
        raise IndexIntegrityError(f"[rag_index] embedding dtype 不匹配: {emb.dtype}（STOP）")

    # 本地 meta 校验
    if meta.get("embedding_config_hash") != embedding_config_hash():
        raise IndexIntegrityError(f"[rag_index] embedding config 不匹配（模型/环境变更）: {icdir}（STOP）")
    if meta.get("commit") != commit:
        raise IndexIntegrityError(f"[rag_index] index commit 不匹配: meta={str(meta.get('commit'))[:8]} want={commit[:8]}（STOP）")
    if hashlib.sha256(chunks_bytes).hexdigest() != meta.get("chunks_sha256"):
        raise IndexIntegrityError(f"[rag_index] chunks.json 哈希不匹配: {icdir}（STOP）")
    if hashlib.sha256(emb.tobytes()).hexdigest() != meta.get("emb_sha256"):
        raise IndexIntegrityError(f"[rag_index] emb.npy 哈希不匹配: {icdir}（STOP）")
    if emb.ndim != 2 or emb.shape[1] != EMBED_DIM:
        raise IndexIntegrityError(f"[rag_index] embedding shape/维度不匹配: {emb.shape}（STOP）")
    chunks = json.loads(chunks_bytes.decode("utf-8"))
    if len(chunks) != meta.get("num_chunks"):
        raise IndexIntegrityError(f"[rag_index] chunk count 不匹配: 实际={len(chunks)} meta={meta.get('num_chunks')}（STOP）")
    if emb.shape[0] != meta.get("num_chunks"):
        raise IndexIntegrityError(f"[rag_index] embedding row count 不匹配: 实际={emb.shape[0]} meta={meta.get('num_chunks')}（STOP）")

    # 绑定冻结 manifest（Phase 4）
    _verify_against_manifest(project, commit, meta, emb, chunks)
    return chunks, emb, meta


def _verify_against_manifest(project, commit, meta, emb, chunks):
    """运行时校验：当前 index 必须与 confirmatory_index_manifest.json 冻结 entry 完全一致。"""
    manifest_path = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_index_manifest.json")
    if not os.path.exists(manifest_path):
        raise IndexIntegrityError(f"[rag_index] confirmatory_index_manifest.json 缺失（STOP）")
    try:
        mf = json.load(open(manifest_path, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise IndexIntegrityError(f"[rag_index] manifest 读取失败: {str(e)[:150]}（STOP）") from e
    entry = None
    for e in mf.get("indexes", []):
        if e.get("project") == project and e.get("commit") == commit:
            entry = e
            break
    if entry is None:
        raise IndexIntegrityError(f"[rag_index] manifest 无此 index entry: {project}@{commit[:8]}（STOP）")
    checks = {
        "repo_url": meta.get("repo_url") == entry.get("repo_url"),
        "commit": commit == entry.get("commit"),
        "index_config_hash": meta.get("index_config_hash") == entry.get("index_config_hash"),
        "embedding_config_hash": meta.get("embedding_config_hash") == entry.get("embedding_config_hash"),
        "chunks_sha256": meta.get("chunks_sha256") == entry.get("chunks_sha256"),
        "emb_sha256": meta.get("emb_sha256") == entry.get("emb_sha256"),
        "num_chunks": meta.get("num_chunks") == entry.get("num_chunks"),
        "emb_row_count": emb.shape[0] == entry.get("emb_row_count"),
        "dim": emb.shape[1] == entry.get("dim"),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        raise IndexIntegrityError(f"[rag_index] 与冻结 manifest 不一致: {bad} ({project}@{commit[:8]})（STOP）")
