# C-06 Full Experiment — Cost Guard（D-011B Step 9，冻结）

| 阈值 | 行为 |
|---|---|
| **Expected** | ≈ **$43**（80 entries × 3 arms × 3 repeats × ~$0.06） |
| **Warning $60** | 仅告警，**不停止** |
| **PAUSE $75** | 暂停新 run，检查：retries、model usage、意外大仓库、记账 bug、剩余预估成本；确认属正常方差后**请求用户批准**再继续 |
| **HARD STOP $90** | 硬停止 |

## 记账口径

- cost guard 累计**所有尝试**的成本（含 infra retry / malformed 纠正性重试），不 reset on restart。
- 每次运行**前**检查累计成本，而非运行后才检查（修复 pilot 的"运行完才检查"缺陷）。
- 含 pilot 已花费 $7.15 与否需明确：本 guard 为 confirmatory 阶段**增量**成本（$43/$60/$75/$90），
  pilot 成本单独记账，不入此 guard。

## 纪律

- **禁止**因 cost guard 选择性删除难样本或坏结果。
- 触发 PAUSE 后不得自行继续，必须用户批准。
