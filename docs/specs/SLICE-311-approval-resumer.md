# SLICE-311 审批恢复器与通知（ADR-0049 切片 2）

状态: active
依据: ADR-0049 已确认；切片 1（SLICE-310）已合并

## 意图

让延迟审批真正闭环，但先做库层机制：

1. `ApprovalNotifier` 端口与 `ApprovalNotice`：提交、决定、过期三类事件。
2. `WebhookNotifier`：HMAC-SHA256 签名、有限重试、失败抛 `NotifierError`。
3. `ApprovalResumer`：轮询审批历史，对每个已决请求调用一次恢复回调，重复轮询不重复触发。
4. `PlanExecutor` 接受可选 notifier：延迟提交与恢复决定时各发一条通知，通知失败不影响计划。

控制台 SSE 与协议适配放到 0049-3，和 A2A/MCP 一起做，避免本切片同时改前端与服务。

## 契约（先改）

- `core.ApprovalNotice`：`kind` 取 `submitted|decided|expired`，含 `request_id`、`tenant`、
  `run_id`、`step_id`、可选 `approved`、`approver`、`expires_at`。
- `core.ApprovalNotifier`：`async def notify(notice) -> None`。
- `WebhookNotifier(url, *, secret, retries=2, backoff=0.2)`：请求头
  `X-ADK-Signature: sha256=<hmac>`，签名对象是请求体字节；非 2xx 与网络错误重试，
  用尽后抛 `NotifierError`。
- `ApprovalResumer(inbox, handler, *, poll_seconds=1.0, batch=50)`：
  `run_once()` 读 `inbox.history(limit=batch, oldest_first=True, since=水位)`，对未见过的
  已决请求调用 `await handler(entry)`；回调异常记录并计入 `failed`，不阻塞其他请求。
  `expired` 只标记已见、不回调（ADR-0049 决定 7）。文件与 Postgres 的 `history`
  增加 `oldest_first` 与 `since` 两个可选参数，默认行为不变。
- 通知有超时上限：执行器 `notify_timeout` 默认 1 秒，通知再慢也不拖住 `PlanPending`。
- 4xx（429 除外）不重试。

## 完成判据

- [ ] 通知模型与端口可用 -> `test_notice_roundtrip`
- [ ] webhook 带正确签名并重试后成功 -> `test_webhook_notifier_signs_and_retries`
- [ ] webhook 用尽重试后抛错 -> `test_webhook_notifier_gives_up`
- [ ] 恢复器每个请求只触发一次 -> `test_resumer_handles_each_decision_once`
- [ ] 恢复回调异常不影响其他请求 -> `test_resumer_survives_handler_errors`
- [ ] 延迟提交发 `submitted` 通知，批准后发 `decided` -> `test_executor_notifies_on_defer_and_decision`
- [ ] 突发超过 batch 时分两次轮询也能排空 -> `test_resumer_drains_a_burst_across_polls`
- [ ] 过期请求不交给恢复回调 -> `test_resumer_skips_expired`
- [ ] 4xx 不重试 -> `test_webhook_rejected_is_not_retried`
- [ ] 慢通知不拖慢延迟返回 -> `test_slow_notifier_does_not_delay_pending`
- [ ] `--full` 门禁通过

## 反例

实现前没有 `ApprovalNotice`、`ApprovalNotifier`、`WebhookNotifier`、`ApprovalResumer`，
以上用例全部失败（`ImportError`）。

## 5 问威胁建模

1. **数据**：通知含 request id、run id、步骤 id 与结果；不含步骤输入正文与凭据。
2. **调用方**：webhook 由运营配置，目标应是可信内网；重试有上限。
3. **信任边界**：HMAC 密钥从环境变量读取，失败不打印密钥。
4. **恶意输入**：webhook 响应不解析，只看状态码。
5. **失败是否泄露信息**：抛 `NotifierError` 只带状态码或异常类型。

## 范围外

- 控制台 SSE、A2A `input-required`、MCP 状态工具（0049-3）。
- 恢复的单赢家抢占与过期强制（0049-4）。

## 证据

- `docs/evidence/SLICE-311-approval-resumer.txt`
