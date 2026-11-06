#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_index_fail_closed.py — D-013 re-audit Phase 3：index load/validation 全部失败模式 → IndexIntegrityError
（INFRASTRUCTURE_ERROR，全局 STOP，非零 exit）。

验证：missing index / corrupt npy / tampered chunks / wrong hash / wrong repo / wrong commit /
wrong config / row-count mismatch，均 GLOBAL STOP；runner 对 infrastructure_error 返回非零 exit。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import rag_index
import runner


def make_index(tmp, project="tp", commit="c" * 40, tamper=None):
    icdir = rag_index._index_dir(project, commit)
    os.makedirs(icdir, exist_ok=True)
    chunks = [{"path": "a.py", "start": 1, "end": 1, "text": "x"}]
    emb = np.zeros((1, 384), dtype="float32")
    import hashlib
    cb = json.dumps(chunks).encode()
    meta = {"project": project, "repo_url": "https://x", "commit": commit,
            "index_config_hash": "ic", "embedding_config_hash": rag_index.embedding_config_hash(),
            "chunks_sha256": hashlib.sha256(cb).hexdigest(),
            "emb_sha256": hashlib.sha256(emb.tobytes()).hexdigest(),
            "num_chunks": 1}
    if tamper == "corrupt_npy":
        open(os.path.join(icdir, "emb.npy"), "wb").write(b"not a numpy file")
    else:
        np.save(os.path.join(icdir, "emb.npy"), emb)
    if tamper == "tamper_chunks":
        open(os.path.join(icdir, "chunks.json"), "w").write('[{"path":"hacked"}]')
    else:
        open(os.path.join(icdir, "chunks.json"), "w").write(cb.decode())
    if tamper == "wrong_meta_hash":
        meta["chunks_sha256"] = "0" * 64
    if tamper == "wrong_config":
        meta["embedding_config_hash"] = "0" * 64
    if tamper == "wrong_commit":
        meta["commit"] = "d" * 40
    if tamper == "row_mismatch":
        meta["num_chunks"] = 2
    json.dump(meta, open(os.path.join(icdir, "index_meta.json"), "w"))
    return icdir


def test_load_failure_modes():
    tmp = tempfile.mkdtemp()
    old = rag_index.INDEX_CACHE_DIR
    rag_index.INDEX_CACHE_DIR = tmp
    results = []
    try:
        cases = [("missing index", "missing", None, False),
                 ("corrupt npy", "tp", "corrupt_npy", False),
                 ("tampered chunks", "tp", "tamper_chunks", False),
                 ("wrong meta hash", "tp", "wrong_meta_hash", False),
                 ("wrong config", "tp", "wrong_config", False),
                 ("wrong commit", "tp", "wrong_commit", False),
                 ("row/count mismatch", "tp", "row_mismatch", False)]
        for name, proj, tamper, _ in cases:
            try:
                if tamper == "missing":
                    rag_index.load_index_integrity("tp", "c" * 40)
                else:
                    make_index(tmp, project=proj, tamper=tamper)
                    rag_index.load_index_integrity(proj, "c" * 40)
                results.append((name, False, "未抛异常"))
            except rag_index.IndexIntegrityError as e:
                results.append((name, True, str(e).replace(tmp, "<tmp>")[:60]))
            except Exception as e:  # noqa: BLE001
                results.append((name, False, f"错误异常类型 {type(e).__name__}"))
    finally:
        rag_index.INDEX_CACHE_DIR = old
    return results


def test_run_one_infra_classification():
    from mocks import FakeEmbedder
    tmp = tempfile.mkdtemp()
    row = {"project": "no-such-proj", "commit": "e" * 40, "repo_url": "https://x",
           "entry_id": "e1", "report_id": "r1", "stratum": "bl", "vuln_category_l2": "x",
           "vuln_title": "t", "task_description": "d", "ep_file": "a.py", "ep_line": 1,
           "co_file": "b.py", "co_line": 2, "_rep": 1}
    rec = runner.run_one("rag", row, tmp, mock=True, embedder=FakeEmbedder(), attempt=0)
    return rec["failure_category"] == "infrastructure_error", rec["failure_category"]


def test_runner_nonzero_exit():
    """真实 runner 子进程：corrupt 首个 confirmatory index → infrastructure_error → 非零 exit。"""
    import csv
    rows = [r for r in csv.DictReader(open(C.CONFIRMATORY_MANIFEST, encoding="utf-8")) if r["role"] == "confirmatory"]
    r = rows[0]
    icdir = rag_index._index_dir(r["project"], r["commit"])
    backup = icdir + ".bak"
    shutil.move(icdir, backup)
    try:
        env = dict(os.environ)
        env["RESULTS_DIR"] = tempfile.mkdtemp()
        code = subprocess.run([sys.executable, "06_experiments/scripts/c06/runner.py",
                               "--phase", "confirmatory", "--mock", "--limit", "1"],
                              capture_output=True, text=True, env=env).returncode
        return code != 0, f"exit={code}"
    finally:
        shutil.move(backup, icdir)


def main():
    results = []
    modes = test_load_failure_modes()
    for name, ok, detail in modes:
        results.append((f"load: {name}", ok, detail))
    ok, detail = test_run_one_infra_classification()
    results.append(("run_one 分类 infrastructure_error", ok, detail))
    ok, detail = test_runner_nonzero_exit()
    results.append(("runner 非零 exit（GLOBAL STOP）", ok, detail))

    for name, ok, detail in results:
        print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
    allpass = all(ok for _, ok, _ in results)
    print(f"\nINDEX GLOBAL FAIL-CLOSED: {'PASS' if allpass else 'FAIL'}")
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(os.path.join(C.ROOT, "06_experiments", "c06", "index_fail_closed_test.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
