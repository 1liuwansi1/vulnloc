# C-06 RAG Latency Protocol（D-013 STEP 5，冻结）

> 冻结两类成本的记账口径。禁止把预计算后的 online latency 称为"包含 indexing 的 end-to-end latency"。

## A. OFFLINE PREPROCESSING（任务盲，正式 run 之外）

> **实际已发生**（precompute_summary.json，D-013 STEP 6）：85 indexes、总 chunks 2,158,130、
> 唯一 chunk 534,123、**跨 commit content-addressed cache 全局命中率 75%**（hits 1,618,556 / misses 539,574）、
> 总墙钟 52,916s（≈14.7h）、CPU user 438,459s。
> 说明：预计算**使用了跨 commit embedding cache**，不是逐 repo 完全清空 cache 的冷构建。

每 (repo, commit) 记录：

| 字段 | 记录位置 |
|---|---|
| source scan time | `index_meta.json.timing.scan_chunk`（与 chunking 合并计时） |
| chunking time | 同上（scan+chunk 合并） |
| number of chunks | `index_meta.json.num_chunks` |
| embedding cache hits | `index_meta.json.chunk_cache.hits` |
| embedding cache misses | `index_meta.json.chunk_cache.misses` |
| embedding compute time | `index_meta.json.timing.embed` |
| index write time | `index_meta.json.timing.write` |
| total preprocessing time | `index_meta.json.timing.total` |
| CPU resources | `precompute_summary.json.cpu_user_seconds / cpu_sys_seconds`（全局累计） |
| peak memory | 未逐 index 记录（limitation，见下） |

## B. ONLINE TASK COST（正式 confirmatory runs 中报告）

RAG 臂每次任务分解：

| 阶段 | 说明 |
|---|---|
| index loading | `load_index_integrity`（读 chunks.json + emb.npy + 校验哈希） |
| BM25 build | 若仍在线执行（当前是：每次 query 在线建 BM25 于 loaded chunks） |
| query embedding | embedder.embed([query]) |
| retrieval | cosine + RRF 融合 |
| context construction | 拼接注入文本 |
| LLM inference | llm.prompt 调用 |
| total online latency | `run_arm_rag` 的 `F`（accounting.F） |

## C. 派生量

**COLD-START END-TO-END COST = offline preprocessing + first online task**（仅首个 (repo,commit) 的第一次 RAG 任务；
且仅在同时拥有"该 index 的 preprocessing 计时"与"首次 online task 计时"的真实数据时才报告，并明确其缓存条件）。

**禁止**：
- 把预计算后的 online latency 宣称为 "包含 indexing 的 end-to-end latency"。
- 把上述 14.7h 预计算描述为 "完全清空所有 cache 后逐 repo cold build"（它用了 75% 跨 commit 复用）。
- 报告未实际测量的阶段细分（如把 scan 与 chunk 拆开，当前实现合并计时为 scan_chunk）。

## 约束

- indexing 已从 online run 中拆出（D-013）；online run 只 load + verify，**不再 cold-build**。
- 若 online run 时 index 缺失/不匹配 → infrastructure error STOP（禁止静默重建）。
- peak memory 未逐 index 记录，记为本协议 limitation（全局 CPU 已记录）。
