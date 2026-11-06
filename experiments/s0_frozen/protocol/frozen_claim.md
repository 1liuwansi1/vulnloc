# C-06 Full Experiment — Frozen Claim（D-011B Step 1）

> 冻结于 confirmatory 运行前。禁止任何比本文件更宽的 claim。

## PRIMARY CLAIM（唯一正式 claim）

> On the pre-specified VulnGym confirmatory sample, using DeepSeek V4 Pro High and a
> matched upper bound on model-visible repository information, our implemented
> **Agentic Exploration** configuration achieves higher **File Recall@5** than our
> implemented deterministic **Pack** configuration.

## 明确禁止的表述

- ❌ "Agentic context acquisition mechanism causally outperforms long context."（因果/泛化过度）
- ❌ "Agent is universally better than RAG."（pilot 中 agent vs rag CI 跨 0）
- ❌ "same token budget"（匹配的是 repository-information budget upper bound，见下）

## 匹配的是什么（严格限定）

匹配的是 **repository-information budget upper bound**（A ≤ 50,000 accounting tokens）。

**不是**：

- ❌ total input tokens（Agent 的 B 约 4× Pack）
- ❌ compute（RAG 有索引构建算力）
- ❌ latency
- ❌ actual information quantity（A 是上限，不是实际注入量）
- ❌ monetary cost（金额接近是偶然，非主匹配变量）

## Agent 臂的定位

Agent 的 iterative interaction / feedback / multi-turn behavior 是完整
**Agentic Exploration strategy** 的组成部分，**不是**被隔离出的单一 causal mechanism。
claim 针对的是"整套策略 vs 确定性打包"的配置对比，而非某个单一机制要素。

## 其他对比的等级（不得越级声明）

- **CONFIRMED**：Agent vs Pack（pilot CI 不含 0；NO_PATH_HINT 子集更强）。
- **SUGGESTIVE**：Agent vs RAG（仅 NO_PATH_HINT 子集）、RAG vs Pack。
- **EXPLORATORY**：漏洞类型交互、路径幻觉率、仓库熟悉度。
