#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pi_rpc_multiturn.py — D-013 Phase 1.1：pi_rpc 多轮 reader 生命周期确定性测试（不调用真实 LLM）。

覆盖：2/5 轮 multi-turn、message_end/agent_settled 顺序、malformed、timeout、delayed、
跨轮消费（previous-turn reader cleanup）。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pi_rpc import PiRpcLLM

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_pi.py")


def make_llm(scenario, turn_timeout=5):
    return PiRpcLLM("test-system", pi_bin=[sys.executable, FAKE, scenario], turn_timeout=turn_timeout)


def test_normal2():
    llm = make_llm("normal2")
    r1 = llm.prompt("q1")
    r2 = llm.prompt("q2")
    llm.close()
    return (r1["text"] == "answer-1" and r1["input"] == 10
            and r2["text"] == "answer-2" and r2["input"] == 20
            and not r1["timed_out"] and not r2["timed_out"]
            and r1["saw_message_end"] and r2["saw_message_end"]), f"r1={r1['text']!r} r2={r2['text']!r}"


def test_normal5():
    llm = make_llm("normal5")
    texts = [llm.prompt(f"q{i}")["text"] for i in range(5)]
    llm.close()
    return texts == ["t1", "t2", "t3", "t4", "t5"], f"texts={texts}"


def test_cross_turn():
    """连续两轮，验证第二轮不会丢失 message_end（旧 reader 不跨轮消费）。"""
    llm = make_llm("cross_turn")
    r1 = llm.prompt("q1")
    r2 = llm.prompt("q2")
    llm.close()
    return (r1["text"] == "first" and r2["text"] == "second"), f"r1={r1['text']!r} r2={r2['text']!r}"


def test_order_swapped():
    """agent_settled 先于 message_end：应 break，saw_message_end=False，text 为空（不视为成功）。"""
    llm = make_llm("order_swapped")
    r = llm.prompt("q")
    llm.close()
    return (r["text"] == "" and not r["saw_message_end"] and not r["timed_out"]), \
        f"text={r['text']!r} saw_message_end={r['saw_message_end']}"


def test_empty_answer():
    llm = make_llm("empty_answer")
    r = llm.prompt("q")
    llm.close()
    return (r["text"] == "" and not r["saw_message_end"] and not r["timed_out"]), \
        f"text={r['text']!r} saw_message_end={r['saw_message_end']}"


def test_malformed():
    """一行非 JSON 垃圾后接正常 message_end：malformed 被跳过，文本正确。"""
    llm = make_llm("malformed")
    r = llm.prompt("q")
    llm.close()
    return (r["text"] == "after-malformed" and r["malformed_events"] == 1), \
        f"text={r['text']!r} malformed={r['malformed_events']}"


def test_timeout():
    """无 agent_settled → timeout。"""
    llm = make_llm("hang", turn_timeout=1)
    t0 = time.time()
    r = llm.prompt("q")
    dt = time.time() - t0
    llm.close()
    return (r["timed_out"] and dt < 4), f"timed_out={r['timed_out']} dt_ok={dt < 4}"


def test_delayed():
    llm = make_llm("delayed", turn_timeout=5)
    r = llm.prompt("q")
    llm.close()
    return (r["text"] == "slow" and not r["timed_out"]), f"text={r['text']!r}"


def main():
    tests = [("2轮 normal multi-turn", test_normal2),
             ("5轮 normal multi-turn", test_normal5),
             ("跨轮消费清理", test_cross_turn),
             ("agent_settled 先于 message_end", test_order_swapped),
             ("空答案(仅 agent_settled)", test_empty_answer),
             ("malformed event 跳过", test_malformed),
             ("timeout", test_timeout),
             ("delayed event", test_delayed)]
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
    print(f"\nRPC MULTI-TURN: {'PASS' if allpass else 'FAIL'}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                       "06_experiments", "c06", "pi_rpc_multiturn_test.json")
    json.dump({"all_pass": allpass, "tests": [{"name": n, "pass": o, "detail": d} for n, o, d in results]},
              open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
