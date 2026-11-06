#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_commit_identity.py — D-013 re-audit Blocker 1：runtime commit successor 验证（synthetic git）。

场景：exact impl → PASS；manifest-only successor → PASS；code/config/stats 变化 → FAIL；
unrelated commit → FAIL；missing runtime → FAIL。
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commit_identity as CI


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)


def make_repo():
    tmp = tempfile.mkdtemp()
    git(tmp, "init", "-q")
    git(tmp, "config", "user.email", "t@t")
    git(tmp, "config", "user.name", "t")
    # impl commit：code.py + config.yaml
    open(os.path.join(tmp, "code.py"), "w").write("x=1\n")
    open(os.path.join(tmp, "config.yaml"), "w").write("name: c06\n")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "impl")
    impl = git(tmp, "rev-parse", "HEAD").stdout.strip()
    frozen_files = {"code": "code.py", "config": "config.yaml"}
    frozen_hashes = {}
    import hashlib
    for name, rel in frozen_files.items():
        frozen_hashes[name] = hashlib.sha256(open(os.path.join(tmp, rel), "rb").read()).hexdigest()
    return tmp, impl, frozen_files, frozen_hashes


def test_exact_impl():
    tmp, impl, ff, fh = make_repo()
    ok, issues = CI.validate_successor(impl, impl, tmp, ff, fh, None)
    return ok, f"issues={issues}"


def test_manifest_only_successor():
    tmp, impl, ff, fh = make_repo()
    # manifest-only successor：只加白名单文件
    os.makedirs(os.path.join(tmp, "06_experiments", "c06"), exist_ok=True)
    open(os.path.join(tmp, "06_experiments", "c06", "attempt2_launch_manifest.json"), "w").write("{}")
    open(os.path.join(tmp, "06_experiments", "c06", "attempt2_launch_manifest.json.sha256"), "w").write("h")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "manifest record")
    runtime = git(tmp, "rev-parse", "HEAD").stdout.strip()
    ok, issues = CI.validate_successor(impl, runtime, tmp, ff, fh, None)
    return ok, f"issues={issues}"


def test_code_change_successor():
    tmp, impl, ff, fh = make_repo()
    open(os.path.join(tmp, "code.py"), "w").write("x=2\n")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "code change")
    runtime = git(tmp, "rev-parse", "HEAD").stdout.strip()
    ok, issues = CI.validate_successor(impl, runtime, tmp, ff, fh, None)
    return (not ok), f"issues={issues}"


def test_config_change_successor():
    tmp, impl, ff, fh = make_repo()
    open(os.path.join(tmp, "config.yaml"), "w").write("name: hacked\n")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "config change")
    runtime = git(tmp, "rev-parse", "HEAD").stdout.strip()
    ok, issues = CI.validate_successor(impl, runtime, tmp, ff, fh, None)
    return (not ok), f"issues={issues}"


def test_stats_change_successor():
    tmp, impl, ff, fh = make_repo()
    # An added statistical implementation is also forbidden for a freeze-only successor.
    open(os.path.join(tmp, "confirmatory_stats.py"), "w").write("changed_statistical_procedure = True\n")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "stats drift")
    runtime = git(tmp, "rev-parse", "HEAD").stdout.strip()
    ok, issues = CI.validate_successor(impl, runtime, tmp, ff, fh, None)
    return (not ok), f"issues={issues}"


def test_unrelated_commit():
    tmp, impl, ff, fh = make_repo()
    # unrelated branch commit
    git(tmp, "checkout", "-q", "--orphan", "other")
    git(tmp, "add", "-A"); git(tmp, "commit", "-q", "-m", "unrelated")
    runtime = git(tmp, "rev-parse", "HEAD").stdout.strip()
    ok, issues = CI.validate_successor(impl, runtime, tmp, ff, fh, None)
    return (not ok), f"ok={not ok} (非 descendant 已拒绝)"


def test_missing_runtime():
    tmp, impl, ff, fh = make_repo()
    ok, issues = CI.validate_successor(impl, "", tmp, ff, fh, None)
    return (not ok), f"issues={issues}"


def main():
    tests = [("exact impl → PASS", test_exact_impl),
             ("manifest-only successor → PASS", test_manifest_only_successor),
             ("code change → FAIL", test_code_change_successor),
             ("config change → FAIL", test_config_change_successor),
             ("stats change → FAIL", test_stats_change_successor),
             ("unrelated commit → FAIL", test_unrelated_commit),
             ("missing runtime → FAIL", test_missing_runtime)]
    results = []
    for name, fn in tests:
        try:
            ok, detail = fn()
            results.append((name, ok, detail))
            print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
        except Exception as e:  # noqa: BLE001
            results.append((name, False, f"EXC {e}"))
            print(f"  [BAD] {name}: EXC {e}")
    allpass = all(ok for _, ok, _ in results)
    print(f"\nRUNTIME COMMIT SUCCESSOR: {'PASS' if allpass else 'FAIL'}")
    import json
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                "06_experiments", "c06", "commit_identity_test.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
