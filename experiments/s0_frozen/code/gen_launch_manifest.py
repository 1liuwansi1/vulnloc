#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_launch_manifest.py — D-013 Phase 5.10：Attempt 2 launch manifest（冻结）。

冻结：git commit、config/sample/schedule/PATH_HINT/index manifest 哈希、evaluator/analysis 实现哈希、
seeds、provider/model/reasoning、Pi 版本、venv 指纹、package 版本、OS/runtime、retry/failure policy。
环境指纹来自实际运行实验的 venv（05_code/venv）+ Pi，而非 harness python3。
"""
import hashlib
import json
import os
import platform
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
C06 = os.path.join(ROOT, "06_experiments", "c06")
VENV_PY = os.path.join(ROOT, "05_code", "venv", "bin", "python")
PI_BIN = "/home/liuwansi/.local/share/pi-node/node-v22.23.2-linux-x64/bin/pi"
OUT = os.path.join(C06, "attempt2_launch_manifest.json")


def sha(path):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import common as C
    return C.sha256_norm(path)


def run(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"<error: {e}>"


def main():
    frozen_files = dict(__import__("common", fromlist=["FROZEN_FILES"]).FROZEN_FILES)
    hashes = {k: sha(os.path.join(ROOT, v)) for k, v in frozen_files.items()}

    git_head = run(["git", "rev-parse", "HEAD"])
    pi_version = run([PI_BIN, "--version"], timeout=60)
    venv_py = run([VENV_PY, "--version"])
    venv_freeze = run([VENV_PY, "-m", "pip", "freeze"], timeout=180)
    venv_freeze_hash = hashlib.sha256(venv_freeze.encode()).hexdigest()

    manifest = {
        "attempt": 2,
        "generated_at": run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]),
        # implementation_commit = 决定正式实验行为的冻结源码/配置 commit（生成本 manifest 时的 HEAD）。
        # 本 manifest 是派生冻结制品；若其后将 manifest 本身提交，那个 commit 是 manifest_record_commit，
        # 不等于 implementation_commit（避免"提交 manifest → HEAD 变 → 再生成"的递归 staleness）。
        "implementation_commit": git_head,
        "manifest_record_commit": None,
        "frozen_file_sha256": hashes,
        "seeds": {"schedule": 20260928, "bootstrap": 20260928, "permutation": 20260928},
        "model": {"provider": "deepseek", "model": "deepseek-v4-pro", "thinking": "high"},
        "pi": {"bin": PI_BIN, "version": pi_version},
        "venv": {"python": venv_py, "pip_freeze_sha256": venv_freeze_hash},
        "packages": {"fastembed": None, "onnxruntime": None, "numpy": None, "tiktoken": None, "rank_bm25": None},
        "os_runtime": {"platform": platform.platform(), "python_harness": sys.version.split()[0],
                       "hostname": platform.node()},
        "retry_policy": "infra-only retry (max 2, 10/20s backoff); 1 formatting correction; model failure = result",
        "failure_policy": "index integrity failure -> IndexIntegrityError -> fail-closed (stop whole experiment); cost guard $60 warn/$75 pause/$90 hard",
        "cost_guard": {"expected": 43.0, "warning": 60.0, "pause": 75.0, "hard": 90.0},
    }
    # package 版本（从 venv 实际 import）
    for pkg in ("fastembed", "onnxruntime", "numpy", "tiktoken", "rank_bm25"):
        try:
            mod = __import__(pkg)
            manifest["packages"][pkg] = getattr(mod, "__version__", "unknown")
        except Exception:
            manifest["packages"][pkg] = None

    blob = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(blob)
    with open(OUT + ".sha256", "w", encoding="utf-8") as f:
        f.write(hashlib.sha256(blob.encode()).hexdigest() + "\n")
    print(f"launch manifest written: {OUT}")
    print(f"implementation_commit={git_head[:12]}  pi={pi_version[:40]}")
    print(f"venv python={venv_py}")
    print(f"packages={manifest['packages']}")


if __name__ == "__main__":
    main()
