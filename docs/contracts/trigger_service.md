# 触发执行服务契约

`serve-triggers` 执行 webhook 触发。调度循环与重试在后续切片。服务只读触发定义。

## `POST /v1/tenants/{tenant}/triggers/{trigger_id}/fire`

请求头：

- `Authorization: Bearer <token>` 必填。服务计算 SHA-256 后与记录的 `webhook_token_hash` 做常量时间比较。
- `Idempotency-Key: <key>` 可选，`^[A-Za-z0-9._-]{1,128}$`。非法 400 `invalid_request`。
- `X-Trace-Id` 可选，`^[A-Za-z0-9._-]{1,128}$`。缺省自动生成。

请求体可选：

```json
{"input": "Run the nightly summary."}
```

- 缺省或空对象时用触发记录的 `input`。
- `input` 必须是非空字符串且不超过 8000 字符，否则 400 `invalid_request`。
- 未知字段 400 `invalid_request`。

成功 200：

```json
{"run_id": "...", "trace_id": "...", "status": "ok", "duplicate": false, "text": "..."}
```

- 重复幂等键且原运行已结束：200，`duplicate: true`，返回原 `run_id`、`trace_id`、`status` 与 `text`（error 时 `text` 为空并带 `error_code`）。
- 重复幂等键且原运行仍在进行：409 `fire_in_progress`。
- 无幂等键时每次请求都运行。

错误：

| 状态 | 错误码 | 条件 |
| --- | --- | --- |
| 400 | `invalid_request` | 请求体、输入或幂等键非法 |
| 401 | `unauthorized` | 令牌缺失或不匹配 |
| 404 | `trigger_not_found` | 触发不存在 |
| 409 | `trigger_disabled` | 触发已停用 |
| 409 | `trigger_kind_mismatch` | 记录是 schedule 触发 |
| 409 | `digest_mismatch` | 注册表记录的 digest 与触发不一致 |
| 409 | `version_retired` | 注册表或生命周期显示已退役 |
| 409 | `approval_required` | manifest 的工具授权声明了需要审批 |
| 409 | `fire_in_progress` | 同幂等键的运行未结束 |
| 429 | `quota_exceeded` | 租户配额超限 |
| 502 | `agent_load_failed` | 工件验签或加载失败 |
| 500 | `run_failed` | 运行失败 |

## 运行语义

- 运行身份是租户下的 `trigger:<trigger_id>`，`kind="service"`。
- 每次成功调用写一条 `trigger.fire` 审计，`status` 为 `ok`、`error` 或 `denied`；`AgentRuntime` 另写 `agent.run`，`source="trigger"`。
- 审计只记输入与结果的哈希，不记原文。
- 401 与未进入运行的请求不写审计。
- 工具守卫按 manifest 授权安装；声明了 `requires_approval` 的授权直接拒绝运行。
- 版本按触发记录的 `agent_id`、`version`、`digest` 固定，不使用 latest。

## `GET /healthz`

开放，返回 `{"status": "ok"}`。

## CLI

`adk-agent serve-triggers`：

- 触发存储：`--triggers-dir DIR` 或 `--trigger-db URL`，都未给时读 `TRIGGER_DATABASE_URL`。
- 注册表与工件：`--registry DIR` 或 `--registry-url URL`；`--artifact-dir DIR` 或 `ARTIFACT_URL`；`--artifact-keys FILE` 或 `ADK_ARTIFACT_KEYS`。
- 授权与审计：`--tool-grants-dir DIR` 或 `GRANT_URL`；`--audit-file`、`--audit-url` 或 `--audit-db`。
- 会话、配额与限流：`--session-db URL`；`--quota-config FILE`；`--rate-limit N --rate-limit-window SECONDS`。
- 监听：`--host`、`--port`。
- 缺少触发存储、注册表、工件存储或信任密钥时退出 1。
