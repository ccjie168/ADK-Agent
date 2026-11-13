# Console HTTP 契约

`GET /` 和 `GET /healthz` 开放。其余 `/api/*` 需要 `Authorization: Bearer <token>`。

鉴权有两种模式。静态 token 模式比较启动时给的单一 token。OIDC 模式验证 JWT，把解析出的 `Principal` 挂到请求上。OIDC 模式下 token 不合法返回 401 `{"error":"unauthorized"}`，签发方不可达返回 503 `{"error":"identity_unavailable"}`。

OIDC 模式下，会话按 principal 的 `subject` 隔离。非 `admin` 身份只能读自己租户的注册表，越权返回 403 `{"error":"tenant_forbidden"}`。策略更新仍由 `policy.update` 的 RBAC 判定，角色来自 token。

## `GET /metrics` -> `text/plain`

Prometheus 文本格式 0.0.4。和其他 `/api/*` 一样需要 bearer token。

- `adk_agent_runs_total{source,tenant,agent,status}`：agent 运行计数，`status` 是 `ok`、`error` 或 `denied`。
- `adk_agent_run_duration_seconds`：summary，只有 `_sum` 和 `_count`。
- `adk_agent_quota_denials_total{tenant,limit}`：配额拒绝计数，`limit` 是 `max_runs` 或 `max_concurrent`。
- `adk_agent_plan_runs_total{tenant,plan,status}`：计划运行计数，由 `PlanExecutor` 注入同一个注册表时才出现。
- `adk_plan_duration_seconds`：计划耗时 summary。

每个控制台进程各自计数，不做跨副本聚合。MCP 和网关的 `/metrics` 不在本契约内。

## `GET /api/agents` -> `[{name, description}]`

## `POST /api/chat`

请求：`{agent, message, session_id?}`
响应：`{session_id, reply, run_id, trace_id}`

租户配额用尽时返回 429 `{"error":"quota_exceeded"}`，并写一条 `agent.run` 的 `denied` 审计，`error_code` 是 `quota_exceeded`。配额在模型调用前检查，超限的请求不会触发模型。配额后端不可用返回 503 `{"error":"quota_unavailable"}`。

可选请求头 `X-Trace-Id`，必须匹配 `^[A-Za-z0-9._-]{1,128}$`。没有合法值时读 `traceparent` 的 trace-id，规则见 `tracing.md`。两者都没有时自动生成。

## `POST /api/chat/stream`

请求同 `/api/chat`。响应 `text/event-stream`。

- `event: progress`，数据是 `ProgressEvent`（见 `progress_event.schema.json`）。
- `event: done`，数据是 `{session_id, reply, run_id, trace_id, dropped}`。
- `event: error`，数据是 `{error, dropped}`，文案固定。配额用尽时是 `{"error":"quota_exceeded","dropped":0}`。
- 每条流最多缓冲 `<sse-queue-size>` 条 `progress`。客户端读得慢时丢弃最旧的 `progress`，保留最新的和终结事件。`dropped` 是被丢掉的条数。
- `progress` 事件可能因慢客户端缺失，终结事件 `done` / `error` 不会丢。
- 鉴权和策略检查在建流前完成，拒绝返回普通 JSON 错误。

## `GET /api/approvals` -> `[ApprovalRequest]`

返回待决的人工审批请求，按 `requested_at` 正序。结构见 `approval_request.schema.json`。

- 已过期的请求不返回。`expires_at` 是请求自带的截止时间，可能为 `null`。
- 未配置审批目录时返回 404 `approvals_not_configured`。
- 非 `admin` 身份只看到自己租户的请求。
- 请求里的 `input` 是待审内容，只在这里返回给有权限的调用方。

## `POST /api/approvals/{request_id}`

请求：`{approved, reason?}`
响应：`ApprovalDecision`，结构见 `approval_decision.schema.json`。`approver` 是当前 principal 的 `subject`，`decided_at` 由服务端生成。

- 请求 id 必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则 400 `unsafe_request_id`。
- `approved` 缺失或不是布尔返回 400 `invalid decision`。
- 请求不存在返回 404 `approval_not_found`。
- 已决请求返回 409 `approval_already_decided`，决定不可改写。
- 已过期且未决的请求返回 410 `approval_expired`。
- 非 `admin` 身份决定其他租户的请求返回 403 `tenant_forbidden`。
- 配置了 `--policy` 时按 `approval.decide:<agent_id>` 判定，拒绝返回 403 `policy_denied`。
- 每次成功决定写一条 `approval.decide` 审计，`target` 是请求 id，`approver` 是审批人，`status` 是 `ok` 或 `denied`。审计不含待审 `input`。
- 未配置审批目录时返回 404 `approvals_not_configured`。

## `GET /api/plans?limit=50` -> `[PlanSummary]`

从当前进程的审计缓冲按 `trace_id` 聚合 `orchestration.run` 事件，按最后事件时间倒序。`limit` 夹在 1 到 200。

```json
{
  "trace_id": "tr1",
  "plan_id": "flow@1.0.0",
  "agent_id": "flow",
  "tenant": "local",
  "status": "ok",
  "error_code": null,
  "started_at": "2026-11-12T10:00:00Z",
  "last_at": "2026-11-12T10:00:01Z",
  "steps": 3,
  "approvals": 1,
  "latency_ms": 120,
  "cost_usd": 0.001
}
```

- `steps` 和 `approvals` 数同一 trace 的 `orchestration.step` 和 `orchestration.approval` 事件。
- 非 `admin` 身份只看到自己租户的计划。
- 计划历史只覆盖当前控制台进程。

## `GET /api/traces/{trace_id}` -> `{trace_id, root, error}`

根是最后一条 `agent.run` 或 `orchestration.run` 事件，`children` 是同一 trace 的其余事件。
非 `admin` 身份只能看到自己租户的事件，别的租户的 trace 视为找不到。
找不到根时 `root` 为 `null`，`error` 为 `trace_not_found`。`trace_id` 必须匹配
`^[A-Za-z0-9._-]{1,128}$`。

## `GET /api/audit?limit=50` -> `[AuditEvent]`

`limit` 上限 200。事件按时间正序，最多返回最近 200 条。非 `admin` 身份只返回自己租户的事件。

事件结构见 `audit_event.schema.json`。

## `GET /api/tenants` -> `[str]`

返回注册表里已发布租户的目录名，按字典序。注册表根目录不存在时返回空数组。非 `admin` 身份只返回自己的租户名。

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
- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 记录损坏返回 500 `registry_corrupt`，响应不含文件路径。
- 未配置注册表返回 404 `registry_not_configured`。

## `GET /api/registry/{tenant}/{id}/{version}/eval` -> `EvalReport`

返回该版本的评测报告，结构见 `eval_report.schema.json`。

- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
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
- 非 `admin` 身份只看到自己租户的 run。
- 运行历史只覆盖当前控制台进程。多副本部署各看各的。

## `GET /api/sessions?agent=<name>` -> `[SessionSummary]`

列出该 agent 在本地用户下的会话，按最后更新时间倒序。

```json
{"session_id": "s1", "last_update_time": "2026-11-12T10:00:00Z"}
```

- 不返回 `state` 和 `events`。
- 只列当前 principal `subject` 的会话。
- 未知 agent 返回 400 `unknown_agent`。
