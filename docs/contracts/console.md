# Console HTTP 契约

`GET /` 和 `GET /healthz` 开放。其余 `/api/*` 需要 `Authorization: Bearer <token>`。

## `GET /api/agents` -> `[{name, description}]`

## `POST /api/chat`

请求：`{agent, message, session_id?}`
响应：`{session_id, reply, run_id, trace_id}`

可选请求头 `X-Trace-Id`，必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则自动生成。

## `GET /api/audit?limit=50` -> `[AuditEvent]`

`limit` 上限 200。事件按时间正序，最多返回最近 200 条。

事件结构见 `audit_event.schema.json`。
