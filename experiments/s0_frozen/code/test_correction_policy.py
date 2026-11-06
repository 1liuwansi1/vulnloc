#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_correction_policy.py — D-013 Phase 1.3 + 1.4：统一 malformed correction + index fail-closed（不调用真实 LLM）。

1.3 验证：三臂统一——空答案不 correction；非空 malformed 仅 1 次 formatting correction；
        合法但错误答案不 correction。
1.4 验证：index 缺失/哈希不匹配 → IndexIntegrityError（fail-closed，不静默重建）。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms
import rag_index


class ScriptedLLM:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
        self.provider, self.model, self.thinking = "mock", "mock", "off"

    def prompt(self, text):
        t = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return {"text": t, "input": 10, "cacheRead": 0, "output": 10, "reasoning": 0,
                "cost": 0.0, "timed_out": False, "crashed": False,
                "saw_message_end": True, "malformed_events": 0}

    def close(self):
        pass


def test_empty_no_correction():
    llm = ScriptedLLM([""])
    parsed, text, B, C, R, CR, cost, fail, err = arms._prompt_until_parse(llm, "q")
    return (fail == "empty_answer" and llm.calls == 1), f"fail={fail} calls={llm.calls}"


def test_malformed_one_correction():
    llm = ScriptedLLM(["garbage not json", "still garbage"])
    parsed, text, B, C, R, CR, cost, fail, err = arms._prompt_until_parse(llm, "q")
    return (fail == "parse_failed" and llm.calls == 2), f"fail={fail} calls={llm.calls}"


def test_malformed_then_valid():
    llm = ScriptedLLM(["garbage", '{"candidate_files":[{"path":"a.py"}]}'])
    parsed, text, B, C, R, CR, cost, fail, err = arms._prompt_until_parse(llm, "q")
    return (fail is None and parsed is not None and llm.calls == 2), f"fail={fail} calls={llm.calls}"


def test_valid_no_correction():
    llm = ScriptedLLM(['{"candidate_files":[{"path":"a.py"}]}'])
    parsed, text, B, C, R, CR, cost, fail, err = arms._prompt_until_parse(llm, "q")
    return (fail is None and llm.calls == 1), f"fail={fail} calls={llm.calls}"


def test_agent_malformed_one_correction():
    # agent 臂：malformed tool → 1 correction → 仍 malformed → invalid_json（2 次调用）
    llm = ScriptedLLM(["garbage", "still garbage"])
    row = {"project": "x", "commit": "a" * 40, "repo_url": "https://x",
           "vuln_title": "t", "task_description": "d"}
    repo = tempfile.mkdtemp()
    ledger = C.Ledger()
    res = arms.run_arm_agent(llm, row, repo, ledger)
    return (res["failure_category"] == "invalid_json" and llm.calls == 2), \
        f"fail={res['failure_category']} calls={llm.calls}"


def test_agent_empty_no_correction():
    # agent 臂：空答案 → 无 correction → invalid_json（1 次调用）
    llm = ScriptedLLM([""])
    row = {"project": "x", "commit": "a" * 40, "repo_url": "https://x",
           "vuln_title": "t", "task_description": "d"}
    repo = tempfile.mkdtemp()
    ledger = C.Ledger()
    res = arms.run_arm_agent(llm, row, repo, ledger)
    return (res["failure_category"] == "invalid_json" and llm.calls == 1), \
        f"fail={res['failure_category']} calls={llm.calls}"


def test_index_missing_fail_closed():
    try:
        rag_index.load_index_integrity("no-such-project", "a" * 40)
        return False, "未抛异常"
    except rag_index.IndexIntegrityError as e:
        return "缺失" in str(e), str(e)[:60]


def test_index_tamper_fail_closed():
    tmp = tempfile.mkdtemp()
    old = rag_index.INDEX_CACHE_DIR
    rag_index.INDEX_CACHE_DIR = tmp
    try:
        proj, commit = "tp", "b" * 40
        icdir = rag_index._index_dir(proj, commit)
        os.makedirs(icdir, exist_ok=True)
        import hashlib
        import numpy as np
        chunks = [{"path": "a.py", "start": 1, "end": 1, "text": "x"}]
        emb = np.zeros((1, 384), dtype="float32")
        cb = json.dumps(chunks).encode()
        meta = {"commit": commit, "embedding_config_hash": rag_index.embedding_config_hash(),
                "chunks_sha256": hashlib.sha256(cb).hexdigest(),
                "emb_sha256": hashlib.sha256(emb.tobytes()).hexdigest(),
                "num_chunks": 1}
        open(os.path.join(icdir, "chunks.json"), "w").write(cb.decode())
        np.save(os.path.join(icdir, "emb.npy"), emb)
        json.dump(meta, open(os.path.join(icdir, "index_meta.json"), "w"))
        # 篡改 chunks
        open(os.path.join(icdir, "chunks.json"), "w").write('[{"path":"hacked"}]')
        try:
            rag_index.load_index_integrity(proj, commit)
            return False, "篡改未检测"
        except rag_index.IndexIntegrityError as e:
            return "哈希不匹配" in str(e), str(e).replace(tmp, "<tmp>")[:60]
    finally:
        rag_index.INDEX_CACHE_DIR = old


def main():
    tests = [("空答案不 correction", test_empty_no_correction),
             ("malformed 仅1次 correction", test_malformed_one_correction),
             ("malformed→correct→valid", test_malformed_then_valid),
             ("valid 不 correction", test_valid_no_correction),
             ("agent malformed 仅1次 correction", test_agent_malformed_one_correction),
             ("agent 空答案不 correction", test_agent_empty_no_correction),
             ("index 缺失 fail-closed", test_index_missing_fail_closed),
             ("index 篡改 fail-closed", test_index_tamper_fail_closed)]
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
    print(f"\nRETRY/FAIL-CLOSED: {'PASS' if allpass else 'FAIL'}")
    out = os.path.join(C.ROOT, "06_experiments", "c06", "correction_policy_test.json")
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
