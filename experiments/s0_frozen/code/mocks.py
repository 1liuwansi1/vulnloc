#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mocks.py — Mock 客户端与伪嵌入（仅用于零 API 成本端到端流水线验证，不产生研究数据）。"""

import json
import hashlib


class MockClient:
    """确定性脚本化客户端（保留旧接口，新代码用 MockLLM）。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        if self.calls == 1:
            return '{"tool":"list_dir","args":{"path":"."}}', {"input": 400, "output": 40}
        return (json.dumps({"candidate_files": [
            {"path": "README.md", "line_start": 1, "line_end": 10, "reason": "mock"}
        ], "notes": "mock run — not research data"}), {"input": 300, "output": 80})


class MockLLM:
    """Mock LLM（prompt 接口）：与 PiRpcLLM 同签名，用于零成本流水线验证。"""

    def __init__(self, system_prompt="", **kw):
        self.calls = 0
        self.agent_mode = "list_dir" in system_prompt
        self.provider, self.model, self.thinking = "mock", "mock", "off"

    def prompt(self, text):
        self.calls += 1
        if self.agent_mode and self.calls == 1:
            return {"text": '{"tool":"list_dir","args":{"path":"."}}',
                    "input": 400, "output": 40, "reasoning": 0, "cost": 0.0,
                    "timed_out": False, "crashed": False, "saw_message_end": True}
        return {"text": json.dumps({"candidate_files": [
                    {"path": "README.md", "line_start": 1, "line_end": 10, "reason": "mock"}],
                    "notes": "mock run — not research data"}),
                "input": 300, "output": 80, "reasoning": 0, "cost": 0.0,
                "timed_out": False, "crashed": False, "saw_message_end": True}

    def close(self):
        pass


class FakeEmbedder:
    """确定性伪嵌入（单次 sha256 → 32 维 + 补零，L2 归一）。仅用于 mock 验证检索管线。"""
    tag = "fake"

    def __init__(self, dim=64):
        self.dim = dim

    def embed(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        return [self._one(t) for t in texts]

    def _one(self, text):
        h = hashlib.sha256(text.encode("utf-8")).digest()
        v = [(h[i] - 127.5) / 127.5 for i in range(min(self.dim, len(h)))]
        if len(v) < self.dim:
            v += [0.0] * (self.dim - len(v))
        norm = (sum(x * x for x in v)) ** 0.5 or 1.0
        return [x / norm for x in v]
