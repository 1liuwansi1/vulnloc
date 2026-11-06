#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common.py — C-06 micro-MVE 共享基础设施（预算记账 / 仓库 / 提示 / 解析 / LLM 客户端）

冻结常量与 budget_contract.md / control_contract.md 一致。修改须在 research_log 记录。
"""

import json
import os
import re
import subprocess
import time
import csv

def sha256_norm(path):
    """CRLF 归一化的 sha256（读磁盘 + CRLF→LF），使磁盘 hash 与 git blob（autocrlf=input）一致。"""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    h.update(data)
    return h.hexdigest()


def sha256_bytes_norm(data):
    import hashlib
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) 
MANIFEST = os.path.join(ROOT, "06_experiments", "c06", "sample_manifest.csv")
REPOS_DIR = os.path.join(ROOT, "05_code", "repos")
C06_DIR = os.path.join(ROOT, "06_experiments", "c06")
LAUNCH_MANIFEST = os.environ.get("C06_LAUNCH_MANIFEST") or os.path.join(C06_DIR, "attempt2_launch_manifest.json")
INDEX_MANIFEST = os.path.join(C06_DIR, "confirmatory_index_manifest.json")
CONFIRMATORY_MANIFEST = os.path.join(C06_DIR, "confirmatory_sample_manifest.csv")
CONFIRMATORY_SCHEDULE = os.path.join(C06_DIR, "confirmatory_run_schedule.csv")

# D-013 冻结产物清单（文件名 -> 相对路径），gen_launch_manifest 与分析 entrypoint 共用。
FROZEN_FILES = {
    "experiment_config": "06_experiments/configs/c06-confirmatory.yaml",
    "sample_manifest": "06_experiments/c06/confirmatory_sample_manifest.csv",
    "run_schedule": "06_experiments/c06/confirmatory_run_schedule.csv",
    "path_hint_annotation": "06_experiments/c06/confirmatory_annotation_manifest.json",
    "index_manifest": "06_experiments/c06/confirmatory_index_manifest.json",
    "index_manifest_sha256_file": "06_experiments/c06/confirmatory_index_manifest.json.sha256",
    "evaluator": "06_experiments/scripts/c06/evaluate.py",
    "common": "06_experiments/scripts/c06/common.py",
    "arms": "06_experiments/scripts/c06/arms.py",
    "pi_rpc": "06_experiments/scripts/c06/pi_rpc.py",
    "runner": "06_experiments/scripts/c06/runner.py",
    "rag_index": "06_experiments/scripts/c06/rag_index.py",
    "analysis_entrypoint": "06_experiments/scripts/c06/analyze_c06_confirmatory.py",
    "stats": "06_experiments/scripts/c06/confirmatory_stats.py",
    "retry_policy": "06_experiments/c06/retry_policy.md",
    "statistical_plan": "06_experiments/c06/statistical_plan.md",
    "cost_guard": "06_experiments/c06/cost_guard.md",
    "frozen_claim": "06_experiments/c06/frozen_claim.md",
}

# ---- 冻结常量 ----
BUDGET_A = 50_000            # repository-information tokens / task / arm
MAX_TOOL_CALLS = 40
MAX_OUTPUT_TOKENS = 4096
TEMPERATURE = 0.0
TREE_CAP_TOKENS = 5_000
READ_LINES_MAX = 400
READ_TOKENS_CAP = 8_000
GREP_MAX_MATCHES = 50
GREP_CTX_LINES = 2
GREP_TOKENS_CAP = 4_000
LIST_MAX_ENTRIES = 200
CHUNK_LINES = 60
CHUNK_OVERLAP = 15
EMBED_TRUNC_TOKENS = 400
RRF_K = 60
MAX_FILE_BYTES = 200_000
DESC_INJECT_CHUNKS = "single-round"
# 成本（ASSUMED，2026-09 公布价，dry run 后按 provider 账单复核）
PRICE_INPUT_PER_MTOK = 3.0     # USD per 1M input tokens
PRICE_OUTPUT_PER_MTOK = 15.0   # USD per 1M output tokens
COST_HARD_STOP_USD = 45.0      # pilot micro-MVE 旧 guard（保留）

# ---- confirmatory full-experiment 成本 guard（D-011B Step 9，冻结）----
COST_EXPECTED_USD = 43.0
COST_WARNING_USD = 60.0   # 仅告警，不停止
COST_PAUSE_USD = 75.0     # 暂停新 run，审计后用户批准再续
COST_HARD_GUARD_USD = 90.0  # 硬停止

SOURCE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".java", ".go", ".rb", ".php",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".rs", ".sh", ".bash", ".zsh", ".sql",
    ".html", ".htm", ".css", ".scss", ".less", ".swift", ".kt", ".kts", ".m", ".mm",
    ".gradle", ".mk", ".cmake", ".tf", ".proto", ".jinja", ".jinja2", ".nix", ".lua",
    ".r", ".pl", ".dart", ".sol",
}
CHUNK_CAP = 40_000  # 每 repo 最大 chunk 数（代码型白名单收紧后预期远低于此）
SKIP_FILENAMES = {".gitignore", ".gitattributes", ".gitmodules", ".npmignore", ".dockerignore"}
SKIP_EXT = {".env", ".lock", ".min.js", ".min.css"}  # 实际按扩展名后缀匹配
BINARY_HINTS = (b"\x00",)

try:
    import tiktoken
    ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    ENC = None


def tok(text: str) -> int:
    if ENC is None:
        return max(1, len(text) // 4)
    # disallowed_special=()：记账 tokenizer 只需计数，不执行特殊 token 语义检查
    # （否则源码中字面量 <|endoftext|> 等会令 tiktoken 抛异常）
    return len(ENC.encode(text, disallowed_special=()))


def truncate_to_tokens(text: str, cap: int, marker=" [TRUNCATED]") -> str:
    """截断到严格 ≤cap 个 accounting tokens（保证每个 block 贡献 ≤ 剩余预算）。
    修复：旧版在 cap < tok(marker) 或跨边界 BPE 时可能返回 >cap 的文本（A=50004/50005 根因）。"""
    if cap <= 0:
        return ""
    if tok(text) <= cap:
        return text
    # 二分搜索：找最大 n 使 tok(text[:n].rstrip() + marker) <= cap
    lo, hi, best = 0, len(text), 0
    for _ in range(40):
        mid = (lo + hi) // 2
        if tok(text[:mid].rstrip() + marker) <= cap:
            best, lo = mid, mid + 1
        else:
            hi = mid
    cand = text[:best].rstrip() + marker
    # 最终保证：跨边界 BPE / marker 自身超 cap 时，逐字符收缩，最坏返回 ""（tok=0）
    while tok(cand) > cap and cand:
        cand = cand[:-1]
    return cand


# ---- manifest / repo ----
def load_manifest(path=MANIFEST):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def repo_dir(project, commit):
    return os.path.join(REPOS_DIR, f"{project}__{commit[:8]}")


def is_source_path(rel):
    base = os.path.basename(rel)
    if base in SKIP_FILENAMES:
        return False
    if rel.startswith(".git"):
        return False
    _, ext = os.path.splitext(base)
    if ext:
        if ext.lower() in {e.lower() for e in SKIP_EXT} or ext.lower().endswith(".min.js") or ext.lower().endswith(".min.css"):
            return False
        return ext.lower() in {e.lower() for e in SOURCE_EXTS}
    return True  # 无扩展名（Dockerfile/Makefile 等），由二进制检测与大小再过滤


def iter_source_files(root):
    """返回 repo 内源文件相对路径（BFS 字典序）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"))
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if not is_source_path(rel):
                continue
            with open(full, "rb") as fh:
                head = fh.read(8192)
            if any(h in head for h in BINARY_HINTS):
                continue
            out.append(rel)
    return sorted(out)


def read_text(root, rel):
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def safe_resolve(root, rel):
    """把仓库内相对路径解析为绝对路径；越界返回 None（. 等于 root 是允许的）。"""
    root = os.path.realpath(root)
    p = os.path.realpath(os.path.join(root, rel))
    if p == root:
        return p
    if not p.startswith(root + os.sep):
        return None
    return p


# ---- 记账 ----
class Ledger:
    def __init__(self):
        self.A = 0            # repo info tokens（投递计费，重复投递重复计）
        self.A_unique = 0     # repo info tokens（按路径去重：每文件首次投递计一次）
        self.unique_paths = set()
        self.blocks = []      # audit: [{path, kind, tokens, ts}]

    def pre_tokens(self, text):
        return tok(text)

    def add_repo_block(self, path, text, kind, cap=None):
        t = tok(text)
        if cap is not None and t > cap:
            text = truncate_to_tokens(text, cap)
            t = tok(text)
        self.A += t
        if path not in self.unique_paths:
            self.unique_paths.add(path)
            self.A_unique += t
        self.blocks.append({"path": path, "kind": kind, "tokens": t, "text": text})
        return text  # 返回实际计入账本的（截断后）文本，保证“记账内容 == 模型所见内容”

    def remaining(self):
        return max(0, BUDGET_A - self.A)


# ---- 提示 / 解析 ----
OUTPUT_SCHEMA_TEXT = (
    'Output ONLY a JSON object (no markdown fences, no commentary) of the form:\n'
    '{"candidate_files":[{"path":"<repo-relative path>","line_start":<int>,"line_end":<int>,"reason":"<short>"}],'
    '"notes":"<optional>"}\n'
    "Rank up to 5 candidate files by likelihood of containing the vulnerable code. "
    "path must be a real repository-relative file path."
)

TASK_HEADER = (
    "You are an expert security analyst performing repository-level vulnerability localization. "
    "Given a vulnerability advisory (title + description) and a repository, identify up to 5 files "
    "most likely to contain the vulnerable code, with line ranges.\n\n" + OUTPUT_SCHEMA_TEXT
)


def task_user_text(row):
    return ("## Vulnerability advisory\n"
            f"Title: {row['vuln_title']}\n\n"
            f"Description:\n{row['task_description']}\n\n"
            "Identify the most likely vulnerable code locations.")


def _try_json(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def _strip_wrappers(t):
    t = re.sub(r"```(?:json)?", "", t)
    t = re.sub(r"</?tool_use>", "", t)
    t = re.sub(r"</?antml:invoke[^>]*>", "", t)
    t = re.sub(r"</?antml:parameter[^>]*>", "", t)
    return t


def parse_final_answer(text):
    """从模型输出提取并校验候选 JSON。返回 dict 或 None。"""
    if not text:
        return None
    t = _strip_wrappers(text.strip())
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        return None
    obj = _try_json(t[i:j + 1])
    if not isinstance(obj, dict):
        return None
    cands = obj.get("candidate_files")
    if not isinstance(cands, list):
        return None
    out = []
    for c in cands[:5]:
        if not isinstance(c, dict) or not isinstance(c.get("path"), str):
            continue
        out.append({"path": c["path"], "line_start": c.get("line_start"), "line_end": c.get("line_end")})
    return {"candidate_files": out, "notes": obj.get("notes")}


def parse_tool_call(text):
    """从 agent 输出解析工具调用 JSON（容错：去标签/fence、修复常见畸形）。"""
    if not text:
        return None
    t = _strip_wrappers(text.strip())
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        return None
    cand = t[i:j + 1]
    obj = _try_json(cand) or _repair_tool_call(cand)
    if isinstance(obj, dict) and isinstance(obj.get("tool"), str) and isinstance(obj.get("args"), dict):
        return obj
    return None


def _repair_tool_call(s):
    # {"tool":"grep", {"args":...}} -> {"tool":"grep","args":{...}}
    s2 = re.sub(r',\s*\{\s*"args"\s*:', ',"args":', s)
    if s2 != s:
        obj = _try_json(s2)
        if obj:
            return obj
    # {"tool": "grep" "args": {...}}（缺逗号）
    s3 = re.sub(r'("\s*:\s*"[^"]*")\s*"args"', r'\1,"args"', s)
    return _try_json(s3)


# ---- LLM 客户端 ----
def make_client(mock=False):
    if mock:
        from mocks import MockClient
        return MockClient(), "mock", "mock-model", {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        model = os.environ.get("C06_MODEL", "claude-sonnet-4-5")
        return anthropic.Anthropic(), "anthropic", model, {"max_tokens": MAX_OUTPUT_TOKENS, "temperature": TEMPERATURE}
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        model = os.environ.get("C06_MODEL", "gpt-4.1")
        return OpenAI(), "openai", model, {"max_tokens": MAX_OUTPUT_TOKENS, "temperature": TEMPERATURE}
    raise RuntimeError("No ANTHROPIC_API_KEY or OPENAI_API_KEY found. "
                       "Set C06_MODEL and provider key via environment variable.")


def chat(client, provider, model, messages, kw, max_tokens=MAX_OUTPUT_TOKENS):
    """统一 chat：返回 (text, usage{input,output})。messages 为 [{role, content}]。"""
    t0 = time.time()
    if provider == "anthropic":
        sys = next((m["content"] for m in messages if m["role"] == "system"), "")
        rest = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        resp = client.messages.create(model=model, system=sys, messages=rest,
                                      max_tokens=max_tokens, temperature=TEMPERATURE)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        usage = {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}
    elif provider == "openai":
        resp = client.chat.completions.create(model=model, messages=[
            {"role": m["role"], "content": m["content"]} for m in messages],
            max_tokens=max_tokens, temperature=TEMPERATURE)
        text = resp.choices[0].message.content or ""
        usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens}
    elif provider == "mock":
        text, usage = client.chat(messages)
    else:
        raise ValueError(provider)
    return text, usage


def est_cost(B, C):
    return B / 1e6 * PRICE_INPUT_PER_MTOK + C / 1e6 * PRICE_OUTPUT_PER_MTOK
