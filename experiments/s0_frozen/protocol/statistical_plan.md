# C-06 Full Experiment — Statistical Plan（D-011B Step 6，冻结）

## 统计单位

- 单位 = **entry**（advisory）。
- 3 repeats **先在 entry 内聚合**（mean）→ 每 entry 每 arm 一个值。
- **禁止**把 80 entries × 3 repeats = 240 当作 240 个独立样本。

## PRIMARY

- 对比：**Agent vs Pack**
- 指标：**File Recall@5**（entry 内 repeats 聚合后）

冻结项：

| 项 | 定义 |
|---|---|
| effect estimator | 配对均值差 δ̄ = mean_i(agent_i − pack_i)，i=entry |
| bootstrap | percentile bootstrap，10,000 次，重采样**entry**（非 run），seed=20260928 冻结 |
| CI | 95% percentile bootstrap CI（报告 δ̄ + CI） |
| paired test | ①精确配对随机化检验（permutation，100,000 次，seed 冻结）为主；②Wilcoxon signed-rank（正确 tie 处理）为辅 |
| 效应量 | Cohen's d_z = δ̄ / SD_entry-level（配对差异的标准差） |

## 仓库 cluster 相关性处理（必须）

confirmatory 样本含 13 个仓库 cluster，openclaw 占 ~60%（真实池分布）。
冻结以下 cluster-aware 分析：

1. **主敏感性**：leave-one-cluster-out，尤其 **leave-openclaw-out**（核心效应是否由单一仓库驱动）。
2. **cluster-robust**：若可行，报告 CRVE（按 repo cluster 聚类）标准误；否则说明理由。
3. **cluster-级聚合（描述性）**：每 cluster 内取均值 → 以 cluster 为单位（n=13，仅描述，不作 confirmatory）。

## Secondary comparisons（提前定义 multiple-testing policy）

Secondary BH 家族严格只有以下 **4 个成员**（D-013 B3：明确已决定口径，不新增检验）：

1. File Recall@5：Agent vs RAG。
2. File Recall@5：RAG vs Pack。
3. Line Recall@5：Agent vs RAG。
4. Line Recall@5：RAG vs Pack。

multiple-testing policy：
- PRIMARY（Agent vs Pack / FR@5）为单一预先指定检验 → **无需校正**。
- 上述四项使用 entry 内 3 repeats 均值的配对差异，按冻结的 paired permutation 方法计算原始 p；
  在这四项内进行 **Benjamini–Hochberg FDR**（q=0.10）校正，报告原始 p 与校正后 q。
- **Invalid Path Rate 仅作描述性分析**，不作假设检验，不进入 BH 家族。
- **PATH_HINT / NO_PATH_HINT 是预先注册的描述性 subgroup 分析**：各子集报告配对差异 + CI；
  子集内配对 p 若报告，仅为描述性结果，不作为额外 confirmatory 检验，不进入 BH 家族。
  CI 重叠情况仅作描述，不强行增加交互检验，也不把 CI 重叠视为正式交互检验。

## 结果报告顺序（preregistered 优先）

1. PRIMARY（agent vs pack / FR@5）+ cluster 敏感性。
2. Secondary（按上表）。
3. 之后才允许 EXPLORATORY 机制分析（明确标注）。
