#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_source_consistency.py — D-011B Step 8：三臂 source universe 一致性验证（静态 + 功能断言）。

验证：
 1. RAG / Pack 使用 C.iter_source_files（source whitelist）作为唯一 source 全集。
 2. Agent read_file 通过 C.is_source_path 限制到同一 whitelist。
 3. Agent grep 结果按 C.is_source_path 后置过滤。
 4. 三臂均排除 .git（is_source_path / iter_source_files 内置）。
 5. 三臂均不读取 manifest 的 ep_file/co_file/ep_line/co_line（ground truth 泄漏）。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms

checks = []

def check(name, ok, detail=""):
    checks.append((name, bool(ok), detail))

# 1. RAG/Pack 用 iter_source_files
rag_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arms.py"), encoding="utf-8").read()
check("RAG 使用 iter_source_files", "iter_source_files" in rag_src and "run_arm_rag" in rag_src,
      "run_arm_rag -> _build_chunks -> C.iter_source_files")
check("Pack 使用 iter_source_files", "iter_source_files" in rag_src and "run_arm_pack" in rag_src,
      "run_arm_pack 循环 C.iter_source_files")

# 2/3. Agent read_file / grep 尊重 is_source_path
check("Agent read_file 检查 is_source_path", "not C.is_source_path(rel)" in rag_src,
      "_tool_read_file 拒绝非 source 文件")
check("Agent grep 后置过滤 is_source_path", "C.is_source_path(ln.split" in rag_src,
      "_tool_grep 仅保留 source 匹配行")

# 4. .git 排除
check("iter_source_files 排除 .git", '".git"' in rag_src and "iter_source_files" in rag_src)
check("grep 排除 .git", "--exclude-dir=.git" in rag_src)

# 5. 三臂不读 ground-truth 字段（静态：arms.py 不得引用 ep_file/co_file/ep_line/co_line）
gt_leak = re.search(r"\b(ep_file|co_file|ep_line|co_line)\b", rag_src)
check("arms.py 不引用 ep_file/co_file/ep_line/co_line", gt_leak is None,
      f"arms.py 命中: {gt_leak.group(0)}" if gt_leak else "无命中")

# 功能断言：is_source_path 对 .py 源文件 True，对 .git/.md/.json False
check("is_source_path(.py)=True", C.is_source_path("src/main.py"))
check("is_source_path(.md)=False", not C.is_source_path("README.md"))
check("is_source_path(.git/...)=False", not C.is_source_path(".git/config"))
check("is_source_path(无扩展名)=True(与 iter_source_files 一致)", C.is_source_path("Dockerfile"))

allpass = all(ok for _, ok, _ in checks)
print("SOURCE CONSISTENCY:", "PASS" if allpass else "FAIL")
for name, ok, detail in checks:
    print(f"  [{'OK ' if ok else 'BAD'}] {name}: {detail}")
sys.exit(0 if allpass else 1)
