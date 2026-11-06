#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arms.py — C-06 三个上下文获取臂（ARM-A agent / ARM-B RAG / ARM-C packing）。

LLM 后端接口：llm.prompt(text) -> {"text","input","output","reasoning","cost"}。
不变式：模型所见仓库上下文 == 记账内容（add_repo_block 返回被计入的截断文本）。
每个臂返回：{answer, raw_text, failure_category, accounting{A,A_unique,B,C,R,D,F,cost}, cost_usd, ...}
"""
import json
import os
import re
import subprocess
import time

import common as C


def _finalize(parsed, raw, failure, acc, extra):
    out = {"answer": parsed, "raw_text": raw, "failure_category": failure,
           "accounting": acc, "cost_usd": round(acc.get("cost", 0.0), 6)}
    out.update(extra)
    return out


def _prompt_until_parse(llm, user, max_corrections=1):
    """单轮臂统一规则（D-013 Phase 1.3）：
    - 空答案（合法但空）→ 不 correction，直接作为结果（empty_answer）。
    - 非空但格式 malformed → 最多 1 次 formatting correction，仍失败 → parse_failed。
    - 合法但错误答案（可解析）→ 直接作为结果，不 correction。"""
    B = C_out = R = CR = cost = 0
    text = ""
    for _ in range(1 + max_corrections):
        try:
            resp = llm.prompt(user)
        except Exception as ex:  # noqa: BLE001
            return None, text, B, C_out, R, CR, cost, "api_error", str(ex)[:200]
        B += resp["input"] + resp.get("cacheRead", 0)
        C_out += resp["output"]
        R += resp["reasoning"]
        CR += resp.get("cacheRead", 0)
        cost += resp["cost"]
        text = resp["text"]
        if resp.get("provider_error"):
            return None, text, B, C_out, R, CR, cost, "api_error", resp.get("error") or "provider/RPC failure"
        if resp.get("timed_out"):
            return None, text, B, C_out, R, CR, cost, "timeout", None
        if resp.get("crashed"):
            return None, text, B, C_out, R, CR, cost, "api_error", "pi process crashed"
        if not resp.get("saw_message_end", True):
            return None, text, B, C_out, R, CR, cost, "api_error", "transport incomplete: no assistant message_end"
        if not text.strip():
            # 合法空答案 → 结果（不 correction）
            return None, text, B, C_out, R, CR, cost, "empty_answer", None
        parsed = C.parse_final_answer(text)
        if parsed is not None:
            return parsed, text, B, C_out, R, CR, cost, None, None
        user = 'Your last reply was not valid JSON. Reply with ONLY the final answer JSON object {"candidate_files":[...]}.'
    return None, text, B, C_out, R, CR, cost, "parse_failed", None


# ================= ARM-A: Agentic Exploration =================
TOOL_DESC = (
    "You may interact with the repository by replying with ONLY a single JSON object per step "
    "(no XML tags, no markdown fences, no commentary):\n"
    '{"tool":"<name>","args":{...}}\n'
    "Available tools:\n"
    ' - list_dir: {"path": "<dir>"} -> list directory entries\n'
    ' - grep: {"pattern": "<regex>", "glob": "<optional, e.g. *.py>"} -> search file contents\n'
    ' - read_file: {"path": "<file>", "start_line": <int>, "end_line": <int>} -> read lines\n'
    "After each tool call you will receive the tool's output. When ready, reply with the final JSON answer only."
)


def _safe_rel(repo, p):
    ap = C.safe_resolve(repo, p)
    return None if ap is None else os.path.relpath(ap, repo).replace(os.sep, "/")


def _tool_list_dir(repo, args, ledger):
    ap = C.safe_resolve(repo, args.get("path", "."))
    if ap is None or not os.path.isdir(ap):
        return "[error: invalid path]"
    entries = sorted(os.listdir(ap))[:C.LIST_MAX_ENTRIES]
    text = "\n".join(e + ("/" if os.path.isdir(os.path.join(ap, e)) else "") for e in entries) or "(empty directory)"
    return ledger.add_repo_block(args.get("path", "."), text, "list", cap=ledger.remaining())


def _tool_grep(repo, args, ledger):
    pattern = str(args.get("pattern", ""))
    if not pattern:
        return "[error: empty pattern]"
    glob = str(args.get("glob", "*")) or "*"
    cmd = ["grep", "-rInE", "-m", str(C.GREP_MAX_MATCHES * 4), "--include", glob,
           "--exclude-dir=.git", "-e", pattern, repo]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return "[grep timed out]"
    out = (r.stdout if r.returncode in (0, 1) else r.stderr).replace(repo.rstrip("/") + "/", "")
    # 源一致性：只保留属于 source universe（is_source_path）的匹配行，与 RAG/Pack 一致
    kept = [ln for ln in out.splitlines() if C.is_source_path(ln.split(":", 2)[0])]
    out = "\n".join(kept)
    if not out.strip():
        out = "(no matches in source files)"
    text = C.truncate_to_tokens(out, min(C.GREP_TOKENS_CAP, ledger.remaining()))
    return ledger.add_repo_block("grep:" + pattern, text, "grep", cap=ledger.remaining())


def _tool_read_file(repo, args, ledger):
    rel = _safe_rel(repo, args.get("path", ""))
    if rel is None:
        return "[error: invalid path]"
    if not C.is_source_path(rel):
        return "[error: not a source file (outside indexed source universe)]"
    if not os.path.isfile(os.path.join(repo, rel)):
        return "[error: not a file]"
    content = C.read_text(repo, rel)
    if content is None:
        return "[error: unreadable]"
    lines = content.splitlines()
    s = max(1, int(args.get("start_line", 1) or 1))
    e = min(len(lines), int(args.get("end_line", len(lines)) or len(lines)))
    if s > e:
        s = e
    seg = lines[s - 1:e]
    note = ""
    if len(seg) > C.READ_LINES_MAX:
        seg = seg[:C.READ_LINES_MAX]
        note = f"\n[read truncated to {C.READ_LINES_MAX} lines]"
    text = "\n".join(f"{s + i}: {ln}" for i, ln in enumerate(seg)) + note
    text = C.truncate_to_tokens(text, min(C.READ_TOKENS_CAP, ledger.remaining()))
    return ledger.add_repo_block(rel, text, "read", cap=ledger.remaining())


def _exec_tool(name, args, repo, ledger):
    return {"list_dir": _tool_list_dir, "grep": _tool_grep, "read_file": _tool_read_file}.get(
        name, lambda repo, a, l: "[error: unknown tool]")(repo, args, ledger)


def run_arm_agent(llm, row, repo, ledger):
    B = C_out = R = CR = cost = 0
    traj = []
    t0 = time.time()
    last_text = ""
    corrected = False  # 当前连续 malformed 已纠正一次（每调用最多 1 次 formatting correction）
    next_msg = C.task_user_text(row)
    for step in range(C.MAX_TOOL_CALLS + 6):
        try:
            resp = llm.prompt(next_msg)
        except Exception as ex:  # noqa: BLE001
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "api_error", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": str(ex)[:300]})
        B += resp["input"] + resp.get("cacheRead", 0)
        C_out += resp["output"]
        R += resp["reasoning"]
        CR += resp.get("cacheRead", 0)
        cost += resp["cost"]
        last_text = resp["text"]
        if resp.get("provider_error"):
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "api_error", acc,
                             {"trajectory": traj, "blocks": ledger.blocks,
                              "error": resp.get("error") or "provider/RPC failure"})
        if resp.get("timed_out"):
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "timeout", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": "turn timeout"})
        if resp.get("crashed"):
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "api_error", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": "pi process crashed"})
        if not resp.get("saw_message_end", True):
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "api_error", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": "transport incomplete: no assistant message_end"})
        tc = C.parse_tool_call(last_text)
        if tc is not None:
            corrected = False  # 有效工具调用，重置纠正标记
            if len(traj) >= C.MAX_TOOL_CALLS or ledger.remaining() <= 0:
                next_msg = "[BUDGET EXHAUSTED — produce your final answer now]"
                continue
            result = _exec_tool(tc["tool"], tc["args"], repo, ledger)
            traj.append({"step": step, "tool": tc["tool"], "args": tc["args"], "result_tokens": C.tok(result)})
            next_msg = "[tool result]\n" + result
            continue
        parsed = C.parse_final_answer(last_text)
        if parsed is not None:
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(parsed, last_text, None, acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": None})
        # malformed（非工具调用非最终 JSON）
        if not last_text.strip():
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "invalid_json", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": "empty answer (no correction)"})
        if corrected:
            acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
                   "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
            return _finalize(None, last_text, "invalid_json", acc,
                             {"trajectory": traj, "blocks": ledger.blocks, "error": "malformed after 1 correction"})
        corrected = True
        next_msg = ('Your last reply was neither a valid tool call nor the final answer JSON. '
                    'Reply with EXACTLY one JSON object: either {"tool":"<name>","args":{...}} '
                    'or the final answer {"candidate_files":[...]}. No tags, no commentary.')
    acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
           "R": R, "CR": CR, "D": len(traj), "F": round(time.time() - t0, 3), "cost": cost}
    return _finalize(None, last_text, "budget_exhausted_no_final", acc,
                     {"trajectory": traj, "blocks": ledger.blocks, "error": None})


# ================= ARM-B: RAG =================
def _tokenize(text):
    return re.findall(r"[a-z0-9_]+", text.lower())


class FastEmbedder:
    tag = "bge"

    def __init__(self):
        from fastembed import TextEmbedding
        self._m = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts):
        import numpy as np
        return np.asarray(list(self._m.embed(list(texts))), dtype="float32")


def _build_chunks(repo):
    chunks = []
    for rel in C.iter_source_files(repo):
        if len(chunks) >= C.CHUNK_CAP:
            break
        content = C.read_text(repo, rel)
        if content is None:
            continue
        lines = content.splitlines()
        step = max(1, C.CHUNK_LINES - C.CHUNK_OVERLAP)
        for s in range(0, len(lines), step):
            if len(chunks) >= C.CHUNK_CAP:
                break
            seg = lines[s:s + C.CHUNK_LINES]
            if any(x.strip() for x in seg):
                chunks.append({"path": rel, "start": s + 1, "end": s + len(seg), "text": "\n".join(seg)})
    return chunks


def _get_index(project, commit, repo, embedder):
    """D-013：加载预计算 RAG index（完整性校验），禁止在线 cold-build。
    若 index 缺失/哈希不匹配/config 不匹配 → 抛 RuntimeError → 上层视为 infrastructure error（STOP，不静默重建）。
    retrieval 算法（BM25 + BGE + RRF）保持不变。"""
    import rag_index
    chunks, emb, meta = rag_index.load_index_integrity(project, commit)
    return chunks, emb


def run_arm_rag(llm, row, repo, ledger, embedder):
    from rank_bm25 import BM25Okapi
    import numpy as np
    import rag_index
    t0 = time.time()
    try:
        chunks, emb = _get_index(row["project"], row["commit"], repo, embedder)
    except rag_index.IndexIntegrityError:
        raise  # fail-closed：index 完整性失败 → 传播到 runner 停止整个实验（不 retry 不继续）
    except Exception as ex:  # noqa: BLE001
        # Only index acquisition/validation is upgraded; later LLM errors retain
        # their existing provider/transport classification and retry policy.
        raise rag_index.IndexIntegrityError(
            f"index load/validation failed: {str(ex)[:300]}"
        ) from ex
    bm25 = BM25Okapi([_tokenize(c["text"]) for c in chunks])
    query = row["vuln_title"] + "\n" + row["task_description"]
    q = _tokenize(query)
    scores = bm25.get_scores(q)
    bm_rank = sorted(range(len(chunks)), key=lambda i: -scores[i])
    qv = np.asarray(embedder.embed([query]), dtype="float32").ravel()
    ev = np.asarray(emb, dtype="float32")
    cos = (ev @ qv) / (np.linalg.norm(ev, axis=1) * (np.linalg.norm(qv) + 1e-9) + 1e-9)
    emb_rank = sorted(range(len(chunks)), key=lambda i: -cos[i])
    score = {}
    for r, i in enumerate(bm_rank):
        score[i] = score.get(i, 0.0) + 1.0 / (C.RRF_K + r + 1)
    for r, i in enumerate(emb_rank):
        score[i] = score.get(i, 0.0) + 1.0 / (C.RRF_K + r + 1)
    order = sorted(score, key=lambda i: -score[i])
    injected, seen, parts = [], set(), []
    for idx in order:
        if ledger.remaining() <= 0:
            break
        key = (chunks[idx]["path"], chunks[idx]["start"])
        if key in seen:
            continue
        seen.add(key)
        text = f"{chunks[idx]['path']}:{chunks[idx]['start']}-{chunks[idx]['end']}\n" + chunks[idx]["text"]
        counted = ledger.add_repo_block(chunks[idx]["path"], text, "rag", cap=ledger.remaining())
        parts.append(counted)
        injected.append({"path": chunks[idx]["path"], "start": chunks[idx]["start"], "end": chunks[idx]["end"]})
    context = "\n\n".join(parts) if parts else "(no context retrieved)"
    user = C.task_user_text(row) + "\n\n## Repository context\n" + context
    parsed, text, B, C_out, R, CR, cost, fail, err = _prompt_until_parse(llm, user)
    acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
           "R": R, "CR": CR, "D": 2, "F": round(time.time() - t0, 3), "cost": cost}
    return _finalize(parsed, text, fail, acc,
                     {"retrieval": {"query": query, "num_chunks": len(chunks), "injected": injected},
                      "blocks": ledger.blocks, "error": err})


# ================= ARM-C: Long Context Packing =================
def run_arm_pack(llm, row, repo, ledger):
    t0 = time.time()
    tree_lines = []
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "node_modules", "__pycache__", ".venv", "venv"))
        rel = os.path.relpath(dirpath, repo)
        depth = rel.count(os.sep) if rel != "." else 0
        for d in dirnames:
            tree_lines.append("  " * depth + d + "/")
        for fn in sorted(filenames):
            tree_lines.append("  " * depth + fn)
        if len(tree_lines) > 4000:
            tree_lines = tree_lines[:4000]
            break
    tree_text = C.truncate_to_tokens("\n".join(tree_lines), C.TREE_CAP_TOKENS)
    parts = [ledger.add_repo_block("tree", tree_text, "tree", cap=ledger.remaining())]
    for rel in C.iter_source_files(repo):
        if ledger.remaining() <= 0:
            break
        content = C.read_text(repo, rel)
        if content is None:
            continue
        counted = ledger.add_repo_block(rel, f"===== {rel} =====\n" + content, "pack", cap=ledger.remaining())
        parts.append(counted)
    context = "\n\n".join(parts)
    user = C.task_user_text(row) + "\n\n## Repository context (packed to budget)\n" + context
    parsed, text, B, C_out, R, CR, cost, fail, err = _prompt_until_parse(llm, user)
    acc = {"A": ledger.A, "A_unique": ledger.A_unique, "B": B, "C": C_out,
           "R": R, "CR": CR, "D": 0, "F": round(time.time() - t0, 3), "cost": cost}
    return _finalize(parsed, text, fail, acc, {"blocks": ledger.blocks, "error": err})
