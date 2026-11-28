# 延迟审批运维手册（ADR-0049）

## 它是什么

需要人工审批的计划步骤不再阻塞调用方：执行器把检查点写成 `waiting_approval` 并返回
`PlanPending`（带 `request_id`），审批人决定后由恢复器用同一 `run_id` 继续执行。

## 组件

| 组件 | 作用 | 位置 |
|---|---|---|
| `PlanExecutor(defer_approvals=True)` | 延迟、写检查点、恢复时校验 `plan_digest` | `src/adk_agent/orchestration/executor.py` |
| `RunCheckpoint.approval_request_id` | 把检查点与审批请求绑定 | 文件/内存与 Postgres 两个后端 |
| `ApprovalResumer` | 轮询审批历史，按 request id 只回调一次 | `src/adk_agent/approval_resumer.py` |
| `ApprovalNotifier` / `WebhookNotifier` | 提交、决定两类通知，HMAC 签名 | `src/adk_agent/notify.py` |

## 开启

- 售后演示：`SUPPORT_DEFER=1`，见 `docs/demo/support-mcp.md`。
- 平台服务：延迟模式是显式开关，默认关闭；关闭时行为与同步审批一致。

## 运维要点

1. **审批存储**：文件后端要求恢复器与写请求的进程看到同一个目录；Postgres 后端共享同
   一个库即可。
2. **恢复器**：必须常驻。进程退出后，已决定但未恢复的请求要等服务重启再恢复；检查点在
   内存后端的演示里不跨重启。
3. **单赢家**：文件部署用 `claim_dir`，恢复器对每个 request id 建独占锁文件
   （`.resume-<id>.lock`），先到者执行、后到者跳过并计入 `skipped`。
   Postgres 多副本部署目前没有跨主机锁，属于已知缺口，接多副本前要加数据库条件抢占。
4. **到期**：请求带 `expires_at`（未给步骤超时时用默认 `defer_ttl_seconds`）。
   过期的决定不会被采纳，执行器记 `approval_timeout` 并放弃该步骤。
5. **通知**：`SUPPORT_NOTIFY_WEBHOOK_URL` 与密钥环境变量；缺密钥只记日志并禁用通知，
   不影响审批与恢复。接收端按 `X-ADK-Signature: sha256=<hmac>` 校验请求体。
6. **观测**：`ApprovalResumer.handled/failed/skipped` 三个计数；审计里看
   `orchestration.deferral`（提交）与 `orchestration.approval`（决定）。

## 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 批准后计划不动 | 恢复器没运行，或用了别的审批目录 | 检查进程与 `--approval-dir` |
| 恢复报 `CheckpointCorrupt` | 计划定义变了，digest 不符 | 换新 `run_id` 或回滚计划 |
| 两个副本都恢复 | 没配 `claim_dir`（或 Postgres 未加锁） | 配 `claim_dir`；多副本等数据库锁 |
| 到期后仍执行 | 用了不带 `expires_at` 的旧请求 | 重新提交一次 |
| 通知全失败 | 密钥缺失或接收端 4xx | 看日志；4xx 不重试 |

## 安全

- 回执只含 `request_id`，不含输入正文或凭据。
- webhook 密钥只从环境变量读取，不落盘、不打印。
- 恢复前校验 `plan_digest`，计划被替换直接拒绝。
