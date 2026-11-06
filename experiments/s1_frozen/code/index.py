"""Complete offline hybrid index; content-addressed namespace and read-only legacy cache reuse."""

from __future__ import annotations
import json, os, time
from pathlib import Path
import numpy as np
from core import (
    ROOT,
    IntegrityError,
    canonical,
    clip,
    digest_file,
    fingerprint,
    digest_bytes,
    tokens,
)
from source import chunks

MODEL = "BAAI/bge-small-en-v1.5"


def embedding_text(text):
    """Byte-compatible frozen embedding truncation; no legacy module imports.

    Memoization avoids repeatedly tokenizing an unchanged midpoint, while
    retaining the original 40-iteration boundary decisions exactly.
    """
    cap = 400
    marker = " [TRUNCATED]"
    if tokens(text) <= cap:
        return text
    lo, hi, best = 0, len(text), 0
    counts = {}
    for _ in range(40):
        mid = (lo + hi) // 2
        if mid not in counts:
            counts[mid] = tokens(text[:mid].rstrip() + marker)
        if counts[mid] <= cap:
            best, lo = mid, mid + 1
        else:
            hi = mid
    candidate = text[:best].rstrip() + marker
    while tokens(candidate) > cap and candidate:
        candidate = candidate[:-1]
    return candidate


class Embedder:
    def __init__(self):
        from fastembed import TextEmbedding

        descriptor = json.loads(
            (
                ROOT / "06_experiments/c06_repair/embedding_compatibility.json"
            ).read_text()
        )
        validate_runtime(descriptor)
        self.model = TextEmbedding(MODEL)
        modeldir = Path(self.model.model._model_dir)
        for filename, field in (
            ("model_optimized.onnx", "onnx_sha256"),
            ("tokenizer.json", "tokenizer_sha256"),
        ):
            if digest_file(modeldir / filename) != descriptor["fingerprint"][field]:
                raise IntegrityError("Embedding model artifact changed: " + filename)

    def embed(self, texts):
        return np.asarray(list(self.model.embed(texts)), dtype="float32")


def validate_runtime(descriptor):
    import fastembed, onnxruntime

    for name, value in (
        ("fastembed", fastembed.__version__),
        ("onnxruntime", onnxruntime.__version__),
        ("numpy", np.__version__),
    ):
        if descriptor["fingerprint"][name] != value:
            raise IntegrityError("Embedding runtime changed: " + name)


def index_identity(universe, cfg):
    descriptor = json.loads(
        (ROOT / "06_experiments/c06_repair/embedding_compatibility.json").read_text()
    )
    return {
        "universe": universe.fingerprint,
        "chunk_lines": cfg["chunk_lines"],
        "chunk_overlap": cfg["chunk_overlap"],
        "embedding": descriptor["fingerprint"],
        "embedding_input": "legacy-truncate-400-cl100k",
        "complete": True,
        "version": 3,
        "embedding_truncation_version": "legacy-exact-v1",
    }


def directory(universe, cfg, mock=False):
    return (
        ROOT
        / "05_code/c06_revision_indices"
        / ("mock" if mock else "real")
        / fingerprint(index_identity(universe, cfg))
    )


def prepare(universe, cfg, embedder=None, mock=False):
    dest = directory(universe, cfg, mock)
    if (dest / "meta.json").exists():
        return load(universe, cfg, mock)[2]
    t = time.monotonic()
    cs = list(chunks(universe, cfg["chunk_lines"], cfg["chunk_overlap"]))
    descriptor = json.loads(
        (ROOT / "06_experiments/c06_repair/embedding_compatibility.json").read_text()
    )
    if not mock:
        validate_runtime(descriptor)
    ecfg = descriptor["legacy_hash"]
    newcache = ROOT / "05_code/c06_revision_embeddings" / ecfg[:16]
    oldcache = ROOT / "05_code/embedding_cache" / ecfg[:16]
    newcache.mkdir(parents=True, exist_ok=True)
    vectors = np.zeros((len(cs), 384), dtype="float32")
    hits = misses = 0
    pending = []
    keys = []

    def flush():
        nonlocal embedder, misses
        if not pending:
            return
        if embedder is None:
            embedder = Embedder()
        batch = embedder.embed([embedding_text(cs[i]["text"]) for i in pending])
        if batch.shape != (len(pending), 384) or not np.isfinite(batch).all():
            raise IntegrityError("Embedding shape/values")
        for j, i in enumerate(pending):
            vectors[i] = batch[j]
            cachepath = newcache / (keys[j] + ".npy")
            temporary = newcache / (keys[j] + ".tmp")
            with temporary.open("wb") as f:
                np.save(f, batch[j])
            os.replace(temporary, cachepath)
            misses += 1
        pending.clear()
        keys.clear()

    for i, c in enumerate(cs):
        if i % 10000 == 0 and i:
            print(
                canonical(
                    {
                        "phase": "embedding-cache",
                        "processed": i,
                        "total": len(cs),
                        "cache_hits": hits,
                        "local_embeddings": misses,
                    }
                ),
                flush=True,
            )
        if mock:
            vectors[i, 0] = 1
            continue
        text = embedding_text(c["text"])
        key = digest_bytes(text.encode() + ecfg.encode())
        candidates = [newcache / (key + ".npy"), oldcache / (key + ".npy")]
        found = next((p for p in candidates if p.exists()), None)
        if found:
            v = np.load(found, allow_pickle=False)
            if (
                not isinstance(v, np.ndarray)
                or v.shape != (384,)
                or not np.isfinite(v).all()
            ):
                raise IntegrityError("Cached embedding corrupt")
            vectors[i] = v
            hits += 1
        else:
            pending.append(i)
            keys.append(key)
            if len(pending) >= 64:
                flush()
    flush()
    dest.mkdir(parents=True, exist_ok=True)
    # meta is the completion marker; partial build never becomes an online index.
    (dest / "chunks.json").write_text(canonical(cs))
    np.save(dest / "emb.npy", vectors)
    meta = {
        "identity": index_identity(universe, cfg),
        "universe_manifest": universe.manifest,
        "mock": mock,
        "chunks": len(cs),
        "source_files": len(universe.files),
        "cache_hits": hits,
        "cache_misses": misses,
        "hashes": {
            name: digest_file(dest / name) for name in ("chunks.json", "emb.npy")
        },
        "seconds": time.monotonic() - t,
    }
    (dest / "meta.json.tmp").write_text(canonical(meta))
    os.replace(dest / "meta.json.tmp", dest / "meta.json")
    return meta


def load(universe, cfg, mock=False):
    if not mock:
        validate_runtime(
            json.loads(
                (
                    ROOT / "06_experiments/c06_repair/embedding_compatibility.json"
                ).read_text()
            )
        )
    dest = directory(universe, cfg, mock)
    try:
        meta = json.loads((dest / "meta.json").read_text())
        if meta["identity"] != index_identity(universe, cfg) or meta["mock"] != mock:
            raise IntegrityError("Index identity")
        if meta["universe_manifest"] != universe.manifest:
            raise IntegrityError("Index universe")
        for name, h in meta["hashes"].items():
            if digest_file(dest / name) != h:
                raise IntegrityError("Index file changed")
        cs = json.loads((dest / "chunks.json").read_text())
        v = np.load(dest / "emb.npy", allow_pickle=False, mmap_mode="r")
        if (
            not isinstance(v, np.ndarray)
            or v.shape != (len(cs), 384)
            or not np.isfinite(v).all()
        ):
            raise IntegrityError("Index vectors")
        # Exact expected chunk coordinates AND text, not just total file/chunk counts.
        expected = chunks(universe, cfg["chunk_lines"], cfg["chunk_overlap"])
        from itertools import zip_longest

        if any(a != b for a, b in zip_longest(cs, expected)):
            raise IntegrityError("Incomplete or changed chunk corpus")
        return cs, v, meta
    except IntegrityError:
        raise
    except Exception as ex:
        raise IntegrityError("Index missing/unreadable: " + str(ex)) from ex


def rank(cs, v, query, embedder):
    import re
    from rank_bm25 import BM25Okapi

    if not cs:
        return []
    tokenize = lambda t: re.findall(r"[a-z0-9_]+", t.lower()) or ["__empty__"]
    bm = BM25Okapi([tokenize(c["text"]) for c in cs]).get_scores(tokenize(query))
    q = embedder.embed([query]).ravel()
    if q.shape != (384,) or not np.isfinite(q).all():
        raise IntegrityError("Query embedding invalid")
    cos = (v @ q) / (np.linalg.norm(v, axis=1) * np.linalg.norm(q) + 1e-9)
    key = lambda i: (cs[i]["path"], cs[i]["start"])
    br = sorted(range(len(cs)), key=lambda i: (-float(bm[i]), key(i)))
    er = sorted(range(len(cs)), key=lambda i: (-float(cos[i]), key(i)))
    score = np.zeros(len(cs))
    bpos = {i: j for j, i in enumerate(br)}
    for ranking in (br, er):
        for j, i in enumerate(ranking):
            score[i] += 1 / (60 + j + 1)
    return sorted(range(len(cs)), key=lambda i: (-score[i], bpos[i], key(i)))
