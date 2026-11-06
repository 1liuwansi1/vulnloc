#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_index_integrity_manifest.py — D-013 Phase 2.5：为每个 confirmatory index 生成完整性 manifest。

每个 index 记录（可审计字段）：canonical repo、full commit、index_config_hash、chunks SHA256、
emb SHA256、chunk count、emb row count、dim、source file count、built_at、build env。
共享 config 段记录：chunking config、tokenizer/embedding model 标识 + artifact 指纹、版本、执行设置、索引实现 git commit。
"""
import csv
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import rag_index

MANIFEST = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_sample_manifest.csv")
OUT = os.path.join(C.ROOT, "06_experiments", "c06", "confirmatory_index_manifest.json")


def git_head():
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=C.ROOT)
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    rows = [r for r in csv.DictReader(open(MANIFEST, encoding="utf-8"))
            if r["role"] in ("confirmatory", "spare")]
    units = {}
    for r in rows:
        units[(r["project"], r["commit"])] = r

    emb_cfg = rag_index.embedding_config_fingerprint()
    shared_config = {
        "chunking": {
            "version": rag_index.CHUNKING_VERSION,
            "chunk_lines": C.CHUNK_LINES,
            "chunk_overlap": C.CHUNK_OVERLAP,
            "chunk_cap": C.CHUNK_CAP,
            "embed_trunc_tokens": C.EMBED_TRUNC_TOKENS,
            "accounting_tokenizer": "cl100k_base",
            "source_exts": sorted(C.SOURCE_EXTS),
            "source_ordering": "os.walk(sorted dirs, sorted files) + final sorted",
            "max_file_bytes": C.MAX_FILE_BYTES,
        },
        "embedding": {
            "model_id": emb_cfg["model_id"],
            "model_snapshot": emb_cfg["model_snapshot"],
            "onnx_sha256": emb_cfg["onnx_sha256"],
            "tokenizer_sha256": emb_cfg["tokenizer_sha256"],
            "dim": emb_cfg["dim"],
            "fastembed": emb_cfg["fastembed"],
            "onnxruntime": emb_cfg["onnxruntime"],
            "numpy": emb_cfg["numpy"],
            "execution": emb_cfg["execution"],
        },
        "indexing_implementation_git_commit": git_head(),
    }

    indexes = []
    missing = []
    for (project, commit), r in sorted(units.items()):
        icdir = rag_index._index_dir(project, commit)
        meta_file = os.path.join(icdir, "index_meta.json")
        if not os.path.exists(meta_file):
            missing.append({"project": project, "commit": commit})
            continue
        meta = json.load(open(meta_file, encoding="utf-8"))
        indexes.append({
            "project": project, "repo_url": meta.get("repo_url"), "commit": commit,
            "cluster_id": r["cluster_id"],
            "index_config_hash": meta.get("index_config_hash"),
            "embedding_config_hash": meta.get("embedding_config_hash"),
            "chunks_sha256": meta.get("chunks_sha256"),
            "emb_sha256": meta.get("emb_sha256"),
            "num_chunks": meta.get("num_chunks"),
            "emb_row_count": meta.get("num_chunks"),
            "dim": meta.get("dim"),
            "num_source_files": meta.get("num_source_files"),
            "built_at": meta.get("built_at"),
            "build_env": meta.get("environment"),
        })

    manifest = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_indexes": len(indexes),
        "expected_indexes": len(units),
        "missing": missing,
        "embedding_config_hash": rag_index.embedding_config_hash(),
        "shared_config": shared_config,
        "indexes": indexes,
    }
    blob = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(blob)
    sha = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    with open(OUT + ".sha256", "w", encoding="utf-8") as f:
        f.write(sha + "\n")
    print(f"indexes={len(indexes)}/{len(units)} missing={len(missing)}")
    print(f"manifest sha256 = {sha}")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
