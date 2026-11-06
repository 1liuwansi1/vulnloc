# C-06 Full Experiment — Retry & Failure Policy（D-011B Step 4，冻结）

## 两类失败（硬性区分）

### Infrastructure failure（可 retry）
- provider / RPC error（网络、连接、HTTP 5xx）
- timeout（RPC 调用超时）
- malformed protocol response（无法解析的 JSON / 协议损坏）

### Model failure（**不可** retry，是结果）
- wrong file（定位到错误文件）
- nonexistent file（预测不存在的路径）
- empty valid answer（空但合法）
- failure to localize vulnerability

## 冻结 retry 参数

| 项 | 值 |
|---|---|
| max retry count（infra） | 2（初始 + 2 次重试） |
| backoff | 10s、20s（指数） |
| RPC timeout | 每轮 600s；stdout 静默超时 600s（真正计时，非读行后检查） |
| malformed-response 纠正性重试 | 1 次（仅当响应可证明为协议损坏，非模型低质量答案） |

## 纪律

- **不得因为模型表现差而 retry**（wrong file / nonexistent / empty / 未定位 = 结果）。
- 每次 retry 必须记录到 event 文件（**保留所有尝试的 cost/result**，禁止覆盖）。
- 纠正性重试与 infra 重试都要在 record 中保留 attempt 序列。
- 任务失败（model failure）同样计入结果与成本，不得丢弃。
