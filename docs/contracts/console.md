# Console HTTP 契约

`GET /` 和 `GET /healthz` 开放。其余 `/api/*` 需要 `Authorization: Bearer <token>`。

鉴权有两种模式。静态 token 模式比较启动时给的单一 token。OIDC 模式验证 JWT，把解析出的 `Principal` 挂到请求上。OIDC 模式下 token 不合法返回 401 `{"error":"unauthorized"}`，签发方不可达返回 503 `{"error":"identity_unavailable"}`。

OIDC 模式下，会话按 principal 的 `subject` 隔离。非 `admin` 身份只能读自己租户的注册表，越权返回 403 `{"error":"tenant_forbidden"}`。策略更新仍由 `policy.update` 的 RBAC 判定，角色来自 token。

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

## `GET /api/tenants` -> `[str]`

返回注册表里已发布租户的目录名，按字典序。注册表根目录不存在时返回空数组。

未配置注册表时返回 404 `{"error":"registry_not_configured"}`。

## `GET /api/registry?tenant=<name>` -> `[RegistryEntry]`

返回该租户的已发布版本，按 `(id, version)` 排序。`tenant` 缺失时用当前 principal 的租户。

```json
{
  "tenant": "team-a",
  "id": "support-bot",
  "version": "1.0.0",
  "digest": "sha256:...",
  "description": "support",
  "published_at": "2026-11-12T10:00:00Z",
  "has_eval_report": true,
  "manifest": {}
}
```

- 非法租户返回 400 `unsafe_tenant`。
- OIDC 模式下，非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 记录损坏返回 500 `registry_corrupt`，响应不含文件路径。
- 未配置注册表返回 404 `registry_not_configured`。

## `GET /api/registry/{tenant}/{id}/{version}/eval` -> `EvalReport`

返回该版本的评测报告，结构见 `eval_report.schema.json`。

- 没有报告返回 404 `eval_report_not_found`。
- 非法路径分量返回 400 `unsafe_tenant`。
- 未配置注册表返回 404 `registry_not_configured`。

## `GET /api/runs?limit=50` -> `[RunSummary]`

从当前进程的审计缓冲按 `run_id` 聚合，按最后事件时间倒序。`limit` 夹在 1 到 200。

```json
{
  "run_id": "r1",
  "trace_id": "tr1",
  "agent_id": "support-bot",
  "tenant": "local",
  "status": "ok",
  "started_at": "2026-11-12T10:00:00Z",
  "last_at": "2026-11-12T10:00:01Z",
  "latency_ms": 120,
  "cost_usd": 0.001,
  "events": 3
}
```

- `status` 取该 run 最后一条事件的 status。
- `latency_ms` 和 `cost_usd` 取最后一条有值的事件，没有则为 `null`。
- `agent_id` 取该 run 的 `agent_ref.id`。
- 运行历史只覆盖当前控制台进程。多副本部署各看各的。

## `GET /api/sessions?agent=<name>` -> `[SessionSummary]`

列出该 agent 在本地用户下的会话，按最后更新时间倒序。

```json
{"session_id": "s1", "last_update_time": "2026-11-12T10:00:00Z"}
```

- 不返回 `state` 和 `events`。
- 只列当前 principal `subject` 的会话。
- 未知 agent 返回 400 `unknown_agent`。
