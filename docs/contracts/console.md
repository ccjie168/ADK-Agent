# Console HTTP 契约

`GET /` 和 `GET /healthz` 开放。其余 `/api/*` 需要 `Authorization: Bearer <token>`。

## `GET /api/agents` -> `[{name, description}]`

## `POST /api/chat`

请求：`{agent, message, session_id?}`
响应：`{session_id, reply, run_id, trace_id}`

可选请求头 `X-Trace-Id`，必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则自动生成。

## `POST /api/chat/stream`

请求同 `/api/chat`。响应 `text/event-stream`。

- `event: progress`，数据是 `ProgressEvent`（见 `progress_event.schema.json`）。
- `event: done`，数据是 `{session_id, reply, run_id, trace_id}`。
- `event: error`，数据是 `{error}`，文案固定。
- 鉴权和策略检查在建流前完成，拒绝返回普通 JSON 错误。

## `GET /api/traces/{trace_id}` -> `{trace_id, root, error}`

根是最后一条 `agent.run` 或 `orchestration.run` 事件，`children` 是同一 trace 的其余事件。
找不到根时 `root` 为 `null`，`error` 为 `trace_not_found`。`trace_id` 必须匹配
`^[A-Za-z0-9._-]{1,128}$`。

## `GET /api/audit?limit=50` -> `[AuditEvent]`

`limit` 上限 200。事件按时间正序，最多返回最近 200 条。

事件结构见 `audit_event.schema.json`。
