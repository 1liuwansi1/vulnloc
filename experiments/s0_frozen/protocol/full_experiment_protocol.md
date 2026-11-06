# C-06 Full Experiment Preregistration（D-011B 后更新）

> 状态：**预注册已冻结。未运行任何 full experiment。** 运行前需用户批准（D-011）。
> 依据：pilot 120 runs（冻结）+ PHASE A 零成本证伪 + D-011B Astra 审计修复。
> 时间：2026-09-29。

## 冻结文档索引（D-011B 产物，逐项可见）

| 审计项 | 冻结文档 |
|---|---|
| Step 1 claim | `frozen_claim.md` |
| Step 2 样本 | `confirmatory_sample_manifest.csv` + `confirmatory_selection_log.md` |
| Step 3 path_hint | `path_hint_annotation_protocol.md` |
| Step 4 retry | `retry_policy.md` |
| Step 5 evaluator | `evaluator_test_cases.json`（PASS）+ `evaluate.py` |
| Step 6 统计 | `statistical_plan.md` |
| Step 7 power | `power_check.py`（N=80 精度）|
| Step 8 源一致性 | `source_consistency.md` + `check_source_consistency.py`（PASS）|
| Step 9 cost guard | `cost_guard.md` + `common.py` 四档常量 |

## 0. RQ（沿用 frozen RQ）
在受控的 **model-visible repository-information budget** 下，上下文获取机制（agentic 探索 / retrieval-augmented / long-context packing）是否实质性影响仓库级漏洞定位？

## 1. 样本（sample inclusion / exclusion）

- **池**：VulnGym `verify == 1` 的 393 entries / **178 advisories / 23 repos**。
- **confirmatory N = 80 独立 advisories**（`confirmatory_sample_manifest.csv`，seed 20260928 冻结抽样；另有 10 spares 补 advisory 抓取失败）。
- **独立单位 = advisory**，≤1 entry/advisory；与 pilot 无共享 report_id（同漏洞禁跨样本）。
- **仓库 cluster**：13 个 repo cluster（openclaw 占 ~60%，真实池分布），cluster id 记入 manifest，cluster-aware 分析见 `statistical_plan.md`。
- **Exclusions**（预先定义，非结果驱动）：
  1. advisory 抓取失败（限流重试后仍不可达）→ 由 spare 顶替；
  2. repo checkout 失败 / commit 不可达；
  3. `ep_file`/`co_file` 无法定位。
- **不得**：因模型预测结果不佳/为空排除 entry；不据难度/表现调整样本。

## 2. Arms（不变）
- **agent**：`list_dir`/regex `grep`/`read_file`(含 range)，≤40 tool calls，text-JSON 工具协议，无 Pi 原生工具。
- **rag**：60 行 chunk / 15 行 overlap；BM25 + `BAAI/bge-small-en-v1.5`，RRF k=60；单轮；索引上限 40,000 chunks。
- **pack**：确定性 source-file packing + tree，直到 A 预算。

## 3. Model / Budget / Retry（不变）
- 通道：Pi RPC；`deepseek-v4-pro`，thinking `high`；每 entry×arm×repeat 独立进程/session。
- **Primary budget = A（model-visible repository info）≤ 50,000 cl100k_base accounting tokens**（口径见 `docs/budget_claim.md`；**不得**简称"同 token 预算"）。
- retry：infra 重试（≤2，10/20s 退避，仅网络/RPC/timeout/无法解析）；malformed-response 纠正性重试；任务失败是结果。重试历史必须保留（修复 pilot 中 event 文件覆盖问题，见 §8）。

## 4. 评价（同一 evaluator，冻结）
- **PRIMARY**：File Recall@5（与 pilot 相同定义）。
- **SECONDARY（预先冻结）**：
  - Line Recall@5
  - **Invalid Path Rate**（由 pilot 发现，本协议前预注册升级为 secondary：预测 path 不存在率）
  - cost / latency / tool calls
- 全部指标在冻结的 raw predictions 上由最终 evaluator 重算；evaluator 版本 + sha256 + commit 记入 evaluation manifest（见 `06_experiments/c06/evaluation_manifest.json`）。

## 5. 统计（预先冻结）
- 分析单元：entry 内 repeats 平均后的配对差异（n = advisory 数）。
- PRIMARY 对比：**agent vs pack**（pilot CONFIRMED）。
- 报告：均值、中位数、bootstrap 95% CI、配对 Cohen's d_z、配对 Wilcoxon（正确实现，修正 pilot 的 tie/方差问题）。
- **预先注册 subgroup**：`PATH_HINT` vs `NO_PATH_HINT`（分类规则已冻结于 `entry_classification.csv` + `phase_a_analysis.py` docstring，**不得据结果修改**）。核心检验：agent>pack 在 NO_PATH_HINT 子集中是否存在。
- **EXPLORATORY subgroup**（报告但不作 confirmatory）：BL vs 传统漏洞类型；仓库熟悉度（FAMOUS/LESSER，n 小，标注局限）。

## 6. 样本量 / repeats（D-011B 冻结：N=80，r=3）
- 证据：repeat-level |diff| 均值 0.025 → repeat 方差极小；entry SD agent-pack=0.414 → 优先加独立 entries。
- **confirmatory N=80 advisories，r=3，3 臂 = 720 runs**（与 pilot 独立，不重跑 pilot）。
- **精度（N=80）**：CI 半宽 ≈0.092；80% power 可检测 δ≈0.13；观测效应 0.26 的 CI ≈[0.17, 0.35]（稳健）。
- **MMD=0.10 的 power 仅 0.58**（需 N=140 才有 81%）——见 `power_check.py`；若用户要求区分 0.10 与 trivial，需 N↑（由用户决策 D-011）。
- 预计成本 ≈$43；cost guard：$60 warning / $75 pause / $90 hard stop。

## 7. Contamination / confounder limitations（预先承认，不事后补救）
- 全部 178 advisories 来自 GitHub Advisory（VulnGym 上游为 >10k stars 仓库）→ **无法声称无训练记忆混杂**；熟悉度分层只是 proxy，不作污染证明。
- PATH_HINT 已作为预注册 subgroup 处理（pilot 发现 8/20 advisory 含路径提示；NO_PATH_HINT 中 agent>pack 反而更强）。
- 前缀缓存成本观察仅限 DeepSeek/当前模型，不泛化（`docs/budget_claim.md`）。

## 8. 实现缺陷修复（D-011B 状态）
- [x] event 文件 retry 覆盖 → 每 attempt 独立 event 文件（`__a<attempt>.jsonl`），attempts_info 保留全部尝试 cost。
- [x] cost guard → 四档（$43/$60/$75/$90）+ 预检查 + 跨重启累计（`_load_existing_cost`）。
- [x] PiRpcLLM 静默超时 → 读线程 + 队列，真正计时。
- [x] truncate_to_tokens 预算边界 → 重写，单测 0 超限（含 cap<marker）。
- [x] 统计修正 → wilcoxon 平均秩+tie 方差、permutation_p、sign_consistency；pilot 重评 agent-pack perm_p=0.0152。
- [x] 三臂 source 一致性 → read_file/grep 限制到 is_source_path；check_source_consistency.py PASS。
- [ ] temperature=0 / max_tokens 上限：**Pi RPC 未确认支持相应 flag，无法强制**（记录为 limitation；repeat |diff| 均值 0.025 经验表明方差低）。

## 9. 运行纪律
- 六要素（git commit/command/config/seed/environment/timestamp）逐 run 记录。
- 失败运行保留 metadata + 日志；不删除失败证据。
- 分析按 `scripts/analyze_results.py` 脚本化；图表由脚本生成。
- 完成后再追加 research_log；重大偏差停下问用户。
