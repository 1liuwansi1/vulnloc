#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
commit_identity.py — D-013 re-audit Blocker 1：runtime commit identity / allowed provenance successor 验证。

规则：
  A. actual_runtime_git_commit == implementation_commit → 允许。
  B. 否则必须同时满足：
     1. runtime 是 implementation 的 descendant（git merge-base --is-ancestor）；
     2. implementation..runtime 的 Git diff 只包含白名单 provenance/freeze artifacts
        （launch manifest + 其 .sha256 sidecar）；
     3. 不允许任何实验行为相关文件变化（code/config/sample/schedule/evaluator/stats/
        runner/arms/pi_rpc/rag_index/statistical_plan 等）；
     4. launch manifest 冻结的行为相关文件 hashes 与 runtime tree 比对一致。
  任何不满足 → FAIL CLOSED。
"""
import hashlib
import os
import subprocess

# 白名单：manifest-only successor 允许变化的文件（launch manifest + sha sidecar）
WHITELIST_SUFFIXES = ("attempt2_launch_manifest.json", "attempt2_launch_manifest.json.sha256")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def is_whitelisted(relpath):
    return relpath.endswith(WHITELIST_SUFFIXES)


def validate_successor(implementation_commit, runtime_commit, repo, frozen_files,
                       frozen_hashes, commit_sha256_for_file):
    """返回 (ok, issues)。frozen_files: {name: relpath}; frozen_hashes: {name: sha256}。"""
    issues = []
    if not runtime_commit:
        return False, ["missing runtime commit"]
    if not implementation_commit:
        return False, ["missing implementation commit"]
    if runtime_commit == implementation_commit:
        return True, []

    # 1. descendant 检查
    r = _git(repo, "merge-base", "--is-ancestor", implementation_commit, runtime_commit)
    if r.returncode != 0:
        return False, [f"runtime 非 implementation 的 descendant: impl={implementation_commit[:12]} runtime={runtime_commit[:12]}"]

    # 2. diff 只含白名单
    r = _git(repo, "diff", "--name-only", implementation_commit, runtime_commit)
    changed = [l for l in r.stdout.splitlines() if l.strip()]
    non_whitelist = [f for f in changed if not is_whitelisted(f)]
    if non_whitelist:
        issues.append(f"非白名单文件变化: {non_whitelist[:5]}")

    # 3+4. 行为相关文件 hash 与 runtime tree 比对（git show <runtime>:<file>，CRLF 归一化）
    for name, rel in frozen_files.items():
        if is_whitelisted(rel):
            continue
        r = _git(repo, "show", f"{runtime_commit}:{rel}")
        if r.returncode != 0:
            issues.append(f"无法读取 runtime 文件 {rel}")
            continue
        normalized = r.stdout.replace("\r\n", "\n").replace("\r", "\n")
        disk_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if disk_hash != frozen_hashes.get(name):
            issues.append(f"行为文件 hash 漂移: {name}")
    return (not issues), issues
