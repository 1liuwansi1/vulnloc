# C-06 Control Contract（控制契约）

**冻结日期**: 2026-09-28（任何 API 运行之前）
**关联**: H-01（hypotheses.md）｜budget_contract.md｜sample_manifest.csv（同目录）
**数据**: VulnGym v0.1.4（commit cd69f7e），仅 `verify==1` entries

---

## 1. 三臂定义（STEP 3，冻结）

### ARM-A — Agentic Exploration（自适应增量获取）

**允许**（模型自主决定下一步）:
- `list_dir(path)`：目录列表（≤200 项，按字典序）
- `grep(pattern, glob, max_results)`：词法搜索（系统 grep -rIn，无 shell 注入；≤50 匹配、每匹配 ≤2 行上下文；结果块记账上限 4k tokens，超出截断并标注）
- `read_file(path, start_line?, end_line?)`：读文件（每次 ≤400 行；结果块记账上限 8k tokens）

**禁止**: embedding 检索；任何 ground-truth 访问（EP/CO/trace/标注 desc 文件不在工具可及范围——工具仅作用于仓库工作目录）；write/edit；网络访问。

**循环**: 模型输出最终 JSON 或 tool_calls>40 或 A 预算耗尽（→ 注入 `[BUDGET EXHAUSTED — produce your final answer now]` 后追加一次收束调用）。

### ARM-B — RAG（查询条件化获取）

**索引**（每 repo@commit 一次，任务盲构建，**不得依据 ground truth 调参**）:
- chunking：源文件（扩展名白名单，与 ARM-C 共用同一列表），60 行/块，15 行重叠
- 词法检索：BM25（rank_bm25，小写化分词）
- 语义检索：本地 embedding——fastembed `BAAI/bge-small-en-v1.5`（确定性、离线、无 API 依赖），每 chunk 前 400 accounting tokens 截断后编码
- **融合（冻结）**: Reciprocal Rank Fusion，RRF_k=60：score = Σ 1/(60+rank_i)；并列时按 BM25 排名、路径字典序
- 查询（冻结）: `task_title + "\n" + task_description`（与任务提示同一冻结文本）

**注入**: 融合排名顺序注入 chunk（去重键 = path+start_line），累计 A 达 50k 停止。**单轮检索**（冻结，不允许多轮改写）。

### ARM-C — Long Context Packing（无条件化批量获取）

**确定性打包规则（冻结）**:
1. 仓库树（仅路径，BFS，字典序）——记账上限 5k tokens，超出截断并标注
2. 源文件按 BFS 顺序（目录内字典序；跳过扩展名黑名单文件与 >200KB 文件），格式 `===== path =====` + 全文
3. 直至 A 预算耗尽；末文件截断标注 `[TRUNCATED]`
4. **不得依据 ground truth 或任务内容选择文件**（规则先于任务固定）

## 2. 控制变量（STEP 4，三臂必须一致）

| 变量 | 值 |
|---|---|
| LLM 与版本 | 同一模型（首个真实 run 时冻结并记入所有 metadata；候选：claude-sonnet-4-5 或 gpt-4.1，取决于可用 key） |
| 采样参数 | temperature=0，top_p=1，max_tokens=4096 |
| 任务文本 | manifest 冻结的 advisory title+description（三臂逐字相同） |
| 仓库状态 | manifest 冻结的 repo_url@commit（blobless clone + 精确 checkout） |
| 输出 schema | 三臂同一 JSON schema（见 §4） |
| A 预算上限 | 50,000 accounting tokens/task/arm |
| 评测脚本 | 同一脚本，arm 盲（输入只有预测与 ground truth） |
| 重复 | 每臂每 entry 2 次独立完整运行（seed 记录；temperature=0 下的差异反映 provider 非确定性） |

**Ground-truth 隔离**: 任何臂的输入中不得出现 EP/CO/trace/标注 desc 派生信息。任务文本即 VulnGym T1 定义（advisory title+description），三臂相同。

## 3. 任务提示模板（冻结）

共享段（三臂逐字相同）: 系统提示含角色设定 + 任务说明 + 输出 schema + 规则（≤5 个候选文件、行范围、仅输出 JSON）。
臂差异段（记账并报告）: ARM-A 附工具使用说明；ARM-B/C 附仓库上下文容器说明。

## 4. 输出 Schema（冻结）

```json
{"candidate_files": [{"path": "<repo-relative>", "line_start": <int>, "line_end": <int>, "reason": "<≤30字>"}, ...],
 "notes": "<可选>"}
```
解析失败 → 最多一次重新请求（固定补救消息）→ 仍失败记 `invalid_json`，该 run File/Line Recall 记 0。

## 5. 指标（STEP 5，冻结；禁止实验后改选 primary）

**PRIMARY — File Recall@5**
- targets(entry) = unique{entry_point.file, critical_operation.file}
- 预测 = 解析后的 candidate_files 路径（≤5，保序）
- FileRecall@5 = |targets ∩ top5| / |targets|，对 20 entries 平均

**SECONDARY**
- Line Recall@5：每个 target 位置 (file, line)（EP 与 CO 各一）命中 = 同文件某预测范围覆盖 line±5；命中率对位置平均
- A（实际消耗）、A_unique（file+line-range 去重账本）、B、C、D、F、G
- failure category（枚举: `invalid_json` / `no_answer` / `budget_exhausted_no_final` / `api_error` / `other`）
- ARM-C 专属: coverage flag（targets 是否全部/部分落在打包窗口内）
- 探索性（分析期标记，非预登记）: 路径幻觉率（预测路径不存在于仓库）、任务文本路径提示标记、BL vs 传统分层的臂差异

## 6. 统计政策（STEP 7，冻结）

micro-MVE 目标**不是**论文级统计证明，**不得**把 p<0.05 作为唯一 PROCEED 条件。

报告:
1. 每 entry 的三臂配对原始结果（全量公开，含 0 分与失败）
2. 臂间配对差异（A−B、A−C、B−C）：均值差 + bootstrap 95% CI（对 entries 重采样 10,000 次）
3. Wilcoxon signed-rank（仅描述性，标注 n=20 的功效限制）
4. 方向一致性（2 次重复间符号是否稳定）
5. 效应量：配对均值差（primary 口径）+ Cliff's delta

**判定规则**:
- **PROCEED**: 存在稳定（两重复方向一致）、非平凡（配对均值差 ≥0.10 File Recall@5 或 CI 不含 0 且有实质意义）、具有机制解释可能性的臂间差异
- **STOP**: 三臂基本等价（所有配对差异 ≤0.05 且方向不稳定），且失败分析未出现有价值机制
- **PIVOT**: 总体差异弱但出现稳定、可解释的特定 failure regime（如某类漏洞仅在某臂可发现）

任何 subgroup 分析（BL vs 传统、coverage flag 等）一律标记 **exploratory**，不得伪装成预登记假设。

## 7. 运行协议

- 全部经 harness：`run_experiment.py`（六要素）+ `analyze_results.py`（provenance）
- dry-run（STEP 9）: 1 entry（不在 20 之内）× 3 arms × 1 repeat；验证记账/解析/评测/日志；据实测更新成本预测；预测 >$50 则停止请求批准
- 运行时支出护栏: 累计 $45 硬停
- 原始保留: 每次模型响应全文、工具轨迹、检索上下文、token 记账、评测结果、运行时元数据、错误——全部落 `$RESULTS_DIR`
