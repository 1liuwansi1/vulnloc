#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pi_rpc.py — Pi RPC headless LLM 客户端（固定 DeepSeek V4 Pro High 通道）。

每个 PiRpcLLM 实例 = 一个独立 pi 进程（--no-session 会话隔离）。
prompt(text) 发送一条用户消息，阻塞到本轮 agent_settled，返回本次助手的
文本 + 该助手消息的 usage（input/output/reasoning/cost）。

并发/生命周期约定（D-013 Phase 1.1 修复）：
  - 每个 PiRpcLLM 只有 **一个** 持久 stdout reader 线程（__init__ 启动，进程生命周期内唯一）。
  - reader 只负责"读行入队"，不解析、不判断轮次边界。
  - prompt() 从共享队列消费，直到本轮 agent_settled（或 timeout/EOF）。
  - 无旧 reader 残留 → 无跨轮消费 message_end；本轮 agent_settled 之后的事件留在队列供下一轮。
  - 显式区分：timeout / crashed(EOF) / malformed event / 空答案（saw_message_end=False）。
"""
import json
import math
import os
import queue
import subprocess
import tempfile
import threading
import time

PI_BIN = "/home/liuwansi/.local/share/pi-node/node-v22.23.2-linux-x64/bin/pi"


class PiRpcLLM:
    def __init__(
        self,
        system_prompt,
        provider="deepseek",
        model="deepseek-v4-pro",
        thinking="high",
        event_log=None,
        turn_timeout=600,
        pi_bin=PI_BIN,
        native_bridge=None,
    ):
        self.event_log = event_log
        self.turn_timeout = turn_timeout
        self.provider, self.model, self.thinking = provider, model, thinking
        self.pi_bin = pi_bin
        self.native_bridge = native_bridge
        self.native_tools = native_bridge is not None
        self.billing_managed = self.native_tools
        prefix = [pi_bin] if isinstance(pi_bin, str) else list(pi_bin)
        cmd = prefix + [
            "--mode",
            "rpc",
            "--no-session",
            "--provider",
            provider,
            "--model",
            model,
            "--thinking",
            thinking,
            "--no-tools",
            "--no-context-files",
            "--no-approve",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--offline",
            "--system-prompt",
            system_prompt,
        ]
        env = os.environ.copy()
        if self.native_tools:
            from pathlib import Path

            cmd[cmd.index("--no-tools")] = "--no-builtin-tools"
            cmd += [
                "--tools",
                "list_dir,grep,read_file",
                "--extension",
                str(native_bridge.extension_path),
            ]
            env["C06_NATIVE_SOCKET"] = native_bridge.socket
        self._stderr_f = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".log"
        )
        self.stderr_path = self._stderr_f.name
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_f,
            text=True,
            bufsize=1,
            env=env,
        )
        self.last_text = None
        self._q = queue.Queue()
        self._stream_closed = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop, name="pi-rpc-reader", daemon=True
        )
        self._reader.start()

    def _read_loop(self):
        """唯一 stdout 读取者：持续读行入队；EOF 或异常时置 stream_closed。"""
        try:
            for line in self.proc.stdout:
                self._q.put(line)
        except Exception:
            pass
        finally:
            self._stream_closed.set()

    def prompt(self, text):
        t0 = time.monotonic()
        deadline_start = t0
        wall_start = time.time()
        self.proc.stdin.write(json.dumps({"type": "prompt", "message": text}) + "\n")
        self.proc.stdin.flush()
        text_blocks = []
        usage = {}
        usage_messages = []
        observed = {}
        observed_messages = []
        timed_out = False
        saw_message_end = False
        malformed_events = 0
        provider_errors = []
        while True:
            remaining = self.turn_timeout - (time.monotonic() - deadline_start)
            if remaining <= 0:
                timed_out = True
                break
            try:
                line = self._q.get(timeout=min(1.0, remaining))
            except queue.Empty:
                if self._stream_closed.is_set():
                    break  # EOF：进程退出（crashed 由下方 poll 判定）
                continue
            if self.event_log is not None:
                self.event_log.write(line)
                self.event_log.flush()
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                malformed_events += 1
                continue
            if not isinstance(ev, dict):
                malformed_events += 1
                continue
            et = ev.get("type")
            # Error signals remain sticky through agent_settled, even if a later
            # event contains text. A provider failure is never a model answer.
            if ev.get("errorMessage") or ev.get("error") or ev.get("finalError"):
                provider_errors.append(
                    str(
                        ev.get("errorMessage")
                        or ev.get("error")
                        or ev.get("finalError")
                    )
                )
            if et in ("error", "provider_error", "rpc_error") or ev.get(
                "stopReason"
            ) in ("error", "aborted"):
                provider_errors.append(f"RPC failure event: {et}")
            if et in ("response", "auto_retry_end") and ev.get("success") is False:
                provider_errors.append(f"{et}: success=false")
            if et == "message_update":
                update = ev.get("assistantMessageEvent", {})
                if isinstance(update, dict) and update.get("type") == "error":
                    provider_errors.append(
                        str(update.get("error") or "assistant stream error")
                    )
            if et in ("message_end", "turn_end"):
                m = ev.get("message", {})
                if isinstance(m, dict) and m.get("role") == "assistant":
                    if m.get("stopReason") in ("error", "aborted") or m.get(
                        "errorMessage"
                    ):
                        provider_errors.append(
                            str(m.get("errorMessage") or m["stopReason"])
                        )
            if et == "message_end":
                m = ev.get("message", {})
                if m.get("role") == "assistant":
                    saw_message_end = True
                    usage = m.get("usage", {})
                    usage_messages.append(usage)
                    observed = {k: m.get(k) for k in ("provider", "model")}
                    observed_messages.append(observed)
                    if self.native_tools:
                        text_blocks = (
                            []
                        )  # Final assistant message, not intermediate prose.
                        deadline_start = time.monotonic()
                    for b in m.get("content", []):
                        if b.get("type") == "text":
                            text_blocks.append(b["text"])
            elif et == "agent_settled":
                break
        text = "".join(text_blocks).strip()
        self.last_text = text
        # Aggregate every assistant completion in this turn, including SDK retries.
        u = {
            key: sum(message.get(key, 0) for message in usage_messages)
            for key in (
                "input",
                "cacheRead",
                "cacheWrite",
                "output",
                "reasoning",
                "totalTokens",
            )
        }
        u["cost"] = {
            "total": sum(
                (message.get("cost") or {}).get("total", 0.0)
                for message in usage_messages
            )
        }
        cost_available = bool(usage_messages) and all(
            isinstance(message.get("cost"), dict)
            and type(message["cost"].get("total")) in (int, float)
            and math.isfinite(message["cost"]["total"])
            and message["cost"]["total"] >= 0
            for message in usage_messages
        )
        crashed = self.proc.poll() is not None
        return {
            "text": text,
            "active_elapsed_seconds": time.monotonic() - t0,
            "wall_elapsed_seconds": time.time() - wall_start,
            "cost_available": cost_available,
            "observed": observed,
            "observed_messages": observed_messages,
            "input": u.get("input", 0),
            "cacheRead": u.get("cacheRead", 0),
            "cacheWrite": u.get("cacheWrite", 0),
            "output": u.get("output", 0),
            "reasoning": u.get("reasoning", 0),
            "totalTokens": u.get("totalTokens", 0),
            "cost": (u.get("cost") or {}).get("total", 0.0),
            "timed_out": timed_out,
            "crashed": crashed,
            "saw_message_end": saw_message_end,
            "provider_error": bool(provider_errors),
            "error": "; ".join(provider_errors)[:2000] if provider_errors else None,
            "malformed_events": malformed_events,
        }

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            self._stderr_f.close()
        except Exception:
            pass
