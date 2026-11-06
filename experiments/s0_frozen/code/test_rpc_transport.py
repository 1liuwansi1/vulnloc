#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_rpc_transport.py — D-013 re-audit Phase 5：RPC transport vs 模型空答案分类（no-LLM synthetic）。

区分：
  A. 完整 assistant message + 合法空内容 → MODEL_OUTPUT（empty_answer，不 infra retry）。
  B. 无 message_end / agent_settled only / 截断流 / partial timeout → INFRASTRUCTURE_ERROR。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import arms


class TransportLLM:
    """脚本化 transport 状态：saw_message_end 与 text 可分别控制。"""
    def __init__(self, seq):
        self.seq = list(seq)
        self.calls = 0
        self.provider, self.model, self.thinking = "mock", "mock", "off"

    def prompt(self, text):
        r = dict(self.seq[min(self.calls, len(self.seq) - 1)])
        self.calls += 1
        r.setdefault("input", 10); r.setdefault("cacheRead", 0); r.setdefault("output", 10)
        r.setdefault("reasoning", 0); r.setdefault("cost", 0.0)
        r.setdefault("timed_out", False); r.setdefault("crashed", False)
        r.setdefault("saw_message_end", True)
        return r

    def close(self):
        pass


def run_rag_like(llm):
    """直接调 _prompt_until_parse（RAG/Pack 单轮路径）。"""
    return arms._prompt_until_parse(llm, "q")


def test_valid_empty():
    llm = TransportLLM([{"text": "", "saw_message_end": True}])
    parsed, text, B, C_, R, CR, cost, fail, err = run_rag_like(llm)
    return (fail == "empty_answer" and llm.calls == 1), f"fail={fail} calls={llm.calls}"


def test_no_message_end():
    llm = TransportLLM([{"text": "", "saw_message_end": False}])
    parsed, text, B, C_, R, CR, cost, fail, err = run_rag_like(llm)
    return (fail == "api_error" and "transport" in (err or "") and llm.calls == 1), f"fail={fail} err={err}"


def test_agent_settled_only():
    llm = TransportLLM([{"text": "", "saw_message_end": False}])
    # agent 路径：run_arm_agent 也检查 saw_message_end
    row = {"project": "x", "commit": "a" * 40, "repo_url": "https://x", "vuln_title": "t", "task_description": "d"}
    repo = tempfile.mkdtemp()
    res = arms.run_arm_agent(llm, row, repo, C.Ledger())
    return (res["failure_category"] == "api_error" and "transport" in (res.get("error") or "")), \
        f"fail={res['failure_category']} err={res.get('error')}"


def test_truncated_stream():
    # 部分事件后无 message_end（simulate：text 有内容但 saw_message_end=False）
    llm = TransportLLM([{"text": "partial json", "saw_message_end": False}])
    parsed, text, B, C_, R, CR, cost, fail, err = run_rag_like(llm)
    return (fail == "api_error" and "transport" in (err or "")), f"fail={fail}"


def test_timeout_after_partial():
    llm = TransportLLM([{"text": "partial", "saw_message_end": False, "timed_out": True}])
    parsed, text, B, C_, R, CR, cost, fail, err = run_rag_like(llm)
    return fail == "timeout", f"fail={fail}"


def main():
    tests = [("valid empty assistant message → empty_answer", test_valid_empty),
             ("no message_end → infrastructure(api_error)", test_no_message_end),
             ("agent_settled only → infrastructure(api_error)", test_agent_settled_only),
             ("truncated stream → infrastructure(api_error)", test_truncated_stream),
             ("timeout after partial → timeout", test_timeout_after_partial)]
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
    print(f"\nRPC TRANSPORT CLASSIFICATION: {'PASS' if allpass else 'FAIL'}")
    import json
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(os.path.join(C.ROOT, "06_experiments", "c06", "rpc_transport_test.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
