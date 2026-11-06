#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fake_pi.py — 用于 pi_rpc 确定性多轮测试的 fake Pi RPC 进程（不调用真实 LLM）。

用法（由测试通过 pi_bin 注入）：
  python fake_pi.py <scenario>

行为：从 stdin 读 prompt JSON（每行 {"type":"prompt","message":...}），
按 scenario 输出脚本化事件序列到 stdout（每个事件一行 JSON）。

scenario 定义在 SCENARIOS 中；每次 prompt 消费一个 turn 脚本。
"""
import json
import sys
import time

SCENARIOS = {
    # 2 轮正常 multi-turn：每轮 message_end + agent_settled
    "normal2": [
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "answer-1"}], "usage": {"input": 10, "output": 1}}},
         {"type": "agent_settled"}],
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "answer-2"}], "usage": {"input": 20, "output": 2}}},
         {"type": "agent_settled"}],
    ],
    # 5 轮连续 multi-turn
    "normal5": [
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": f"t{i}"}], "usage": {"input": i, "output": i}}},
         {"type": "agent_settled"}] for i in range(1, 6)
    ],
    # message_end 与 agent_settled 顺序变化：agent_settled 在 message_end 之前
    "order_swapped": [
        [{"type": "agent_settled"},
         {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "late-message"}], "usage": {"input": 1, "output": 1}}}],
    ],
    # 只有 agent_settled 无 message_end（空答案）
    "empty_answer": [
        [{"type": "agent_settled"}],
    ],
    # malformed：先输出一行非 JSON 垃圾，再正常
    "malformed": [
        ["this is not json",
         {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "after-malformed"}], "usage": {"input": 5, "output": 5}}},
         {"type": "agent_settled"}],
    ],
    # timeout：永不输出 agent_settled（挂起）
    "hang": [
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "partial"}]}}],  # 无 agent_settled
    ],
    # delayed：每个事件间隔延迟
    "delayed": [
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "slow"}]}, "delay": 0.3},
         {"type": "agent_settled", "delay": 0.2}],
    ],
    # 跨轮消费测试：第 1 轮正常，第 2 轮正常（验证无旧 reader 抢占）
    "cross_turn": [
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}], "usage": {"input": 1, "output": 1}}},
         {"type": "agent_settled"}],
        [{"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "second"}], "usage": {"input": 2, "output": 2}}},
         {"type": "agent_settled"}],
    ],
}


# Successful empty completion and explicit provider/runtime failure signals.
_empty = {"role": "assistant", "content": [], "stopReason": "stop",
          "usage": {"input": 0, "output": 0, "cost": {"total": 0.001}}}
SCENARIOS.update({
    "complete_empty": [[{"type": "message_end", "message": _empty}, {"type": "agent_settled"}]],
    "provider_503": [[{"type": "message_end", "message": dict(_empty, stopReason="error", errorMessage="503 synthetic service unavailable")},
                       {"type": "auto_retry_end", "success": False, "finalError": "503 synthetic service unavailable"}, {"type": "agent_settled"}]],
    "stop_error": [[{"type": "message_end", "message": dict(_empty, stopReason="error")}, {"type": "agent_settled"}]],
    "error_message": [[{"type": "message_end", "message": dict(_empty, errorMessage="synthetic provider failure")}, {"type": "agent_settled"}]],
    "retry_failed": [[{"type": "message_end", "message": _empty}, {"type": "auto_retry_end", "success": False}, {"type": "agent_settled"}]],
    "rpc_failed": [[{"type": "response", "command": "prompt", "success": False, "error": "synthetic RPC failure"}, {"type": "agent_settled"}]],
    "stream_error": [[{"type": "message_update", "assistantMessageEvent": {"type": "error", "error": "synthetic stream failure"}},
                       {"type": "message_end", "message": _empty}, {"type": "agent_settled"}]],
    "aborted": [[{"type": "message_end", "message": dict(_empty, stopReason="aborted")}, {"type": "agent_settled"}]],
    "provider_event": [[{"type": "provider_error", "errorMessage": "synthetic provider failure"}, {"type": "agent_settled"}]],
})


def main():
    scenario = sys.argv[1]
    scripts = SCENARIOS[scenario]
    idx = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "prompt":
            continue
        if idx >= len(scripts):
            # 超过脚本的 prompt：挂起（模拟无响应）
            time.sleep(60)
            continue
        for item in scripts[idx]:
            delay = 0.0
            if isinstance(item, dict):
                delay = item.pop("delay", 0.0)
                out = item
            else:
                out = item  # 字符串 = 原始非 JSON 行（测试 malformed）
            if delay:
                time.sleep(delay)
            sys.stdout.write((out if isinstance(out, str) else json.dumps(out)) + "\n")
            sys.stdout.flush()
        idx += 1


if __name__ == "__main__":
    main()
