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
- `event: done`，数据是 `{session_id, reply, run_id, trace_id, dropped}`，`dropped` 总是存在。
- `event: error`，数据是 `{error}`，文案固定。丢弃过进度时额外带 `dropped`（正整数）。配额用尽时是 `{"error":"quota_exceeded"}`。
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
找不到根时 `root` 为 `null`，`error` 为 `trace_not_found`。配置了 `--audit-url` 时服务不可用返回 502 `audit_unavailable`。`trace_id` 必须匹配
`^[A-Za-z0-9._-]{1,128}$`。

## `GET /api/audit?limit=50` -> `[AuditEvent]`

`limit` 上限 200。事件按时间正序，最多返回最近 200 条。非 `admin` 身份只返回自己租户的事件。配置了 `--audit-url` 时从审计服务读取，服务不可用返回 502 `audit_unavailable`。

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
  "manifest": {},
  "artifact": {"digest": "sha256:...", "size": 450, "key_id": "publisher-1", "status": "verified"},
  "lifecycle": {"status": "published", "changed_at": null, "changed_by": null, "reason": ""}
}
```

`lifecycle` 是 ADR-0010 的状态；没有状态行时是默认的 `published`。`artifact` 为 `null` 表示该版本没有工件。`status` 是 `verified`、`untrusted`、`unknown`（控制台没有配置可信密钥）或 `unsigned`（工件没有签名）。

- 非法租户返回 400 `unsafe_tenant`。
- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 记录损坏返回 500 `registry_corrupt`，响应不含文件路径。
- 生命周期存储不可用返回 503 `lifecycle_unavailable`。
- 未配置注册表返回 404 `registry_not_configured`。

## `GET /api/registry/{tenant}/{id}/{version}/eval` -> `EvalReport`

返回该版本的评测报告，结构见 `eval_report.schema.json`。

- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 没有报告返回 404 `eval_report_not_found`。
- 非法路径分量返回 400 `unsafe_tenant`。
- 未配置注册表返回 404 `registry_not_configured`。

## `POST /api/registry/load` -> `{"name", "version", "loaded"}`

按需把一个已发布版本加载成聊天目标。控制台进程内执行，不是沙箱。

```json
{"tenant": "team-a", "id": "support-bot", "version": "1.0.0"}
```

成功返回 200 `{"name": "support-bot", "version": "1.0.0", "loaded": true}`。同名 agent 已在控制台加载时返回 200 且 `loaded=false`，不切换版本。

- 需要注册表、工件存储和可信公钥。缺注册表返回 404 `registry_not_configured`，缺存储返回 503 `artifact_store_unavailable`，缺公钥返回 503 `artifact_trust_unavailable`。
- 请求体不是 JSON 或字段不合法返回 400 `invalid_request`。
- 非 `admin` 身份加载其他租户返回 403 `tenant_forbidden`。
- 版本不存在返回 404 `not_found`。
- 该版本没有工件返回 409 `artifact_missing`；签名缺失或不可信返回 409 `artifact_untrusted`。
- 同名 agent 已按另一版本按需加载返回 409 `name_conflict`。
- 版本已退役返回 409 `version_retired`；`deprecated` 版本仍可加载。
- 已加载数量达到 `--max-loaded-agents` 返回 409 `load_limit`。
- 工件无法加载成同名 ADK agent 返回 500 `load_failed`。
- 生命周期存储不可用返回 503 `lifecycle_unavailable`。
- 成功加载写一条 `agent.load` 审计，`status=ok`，`target` 是 agent 名，`tenant` 是调用方的租户（审计事件要求租户等于 principal 的租户）。

## `GET /api/tools?tenant=<name>` -> `[ToolEntry]`

只读工具目录。每个条目附带该租户已发布版本里引用它的 agent。

```json
{
  "tool_id": "crm.read",
  "description": "read a CRM record",
  "source": "function",
  "data_classes": ["internal"],
  "requires_approval": false,
  "tenant": null,
  "granted_agents": [{"id": "support-bot", "version": "1.0.0"}]
}
```

- 目录由 `console --tool-catalog FILE` 和已配置的连接器存储共同提供。两者都未配置返回 404 `tool_catalog_not_configured`。
- `tenant` 为 `null` 的条目对所有租户可见；其他条目只在同名租户出现。
- `tenant` 缺失时用当前 principal 的租户。非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 连接器条目只来自已启用的连接器，与工具网关暴露的范围一致。`source` 为 `connector`，`tool_id` 等于 `connector_id`，`description` 为 `<kind> connector to <base_url>`，`data_classes` 取连接器定义，`requires_approval` 为 `false`，`tenant` 取连接器租户（全局连接器为 `null`）。
- 同一 `tool_id` 同时出现在静态目录和连接器存储时，静态条目优先，连接器条目被跳过。
- 连接器存储不可达返回 503 `connector_store_unavailable`。
- `granted_agents` 来自该租户注册表记录中 `manifest.tool_grants` 的同名工具，按 `(id, version)` 排序。没有注册表时为空列表；注册表损坏返回 500 `registry_corrupt`。
- 结果按 `tool_id` 排序。

## `GET /api/connectors?tenant=<name>` -> `[ConnectorSpec]`

只读连接器列表，按 `connector_id` 排序。全局连接器（`tenant` 为 `null`）对所有租户可见。

- 由 `console --connectors-dir DIR`（文件存储）或已有的 `--registry-url`（控制面）提供；都未配置时返回 404 `connectors_not_configured`。
- `tenant` 缺失时用当前 principal 的租户；非 `admin` 跨租户 403 `tenant_forbidden`。
- 存储不可达返回 503 `connector_store_unavailable`。

## `POST /api/connectors` -> `ConnectorSpec`

```json
{
  "connector_id": "crm",
  "tenant": "acme",
  "kind": "http",
  "base_url": "https://crm.example.com",
  "auth_ref": "secret://crm/token",
  "methods": ["GET"],
  "path_prefixes": ["/v1/crm/"],
  "data_classes": ["internal"],
  "timeout_seconds": 10,
  "max_response_bytes": 1048576
}
```

- 只有 `admin` 能注册，非 admin 返回 403 `forbidden`。
- 请求体不是 JSON 或不是对象 400 `invalid_request`；`ConnectorSpec` 校验失败 400 `invalid_connector`。
- 同 id 同定义重发 201，幂等；不同定义 409 `connector_conflict`。
- 成功 201，写 `connector.register` 审计，`target` 是 `<tenant>/<id>` 或 `global/<id>`。
- 未配置存储 404 `connectors_not_configured`；存储不可达 503 `connector_store_unavailable`。

## `POST /api/connectors/{connector_id}/disable` -> `ConnectorSpec`

- 只有 `admin` 能停用，非 admin 403 `forbidden`。
- 不存在 404 `connector_not_found`。
- 成功 200，重复停用幂等，写 `connector.disable` 审计。
- 未配置存储 404 `connectors_not_configured`；存储不可达 503 `connector_store_unavailable`。

## `POST /api/connectors/{connector_id}/check` -> `ConnectorHealth`

对一个连接器发出受约束的探测请求。

```json
{
  "connector_id": "crm",
  "status": "healthy",
  "status_code": 200,
  "latency_ms": 42,
  "checked_at": "2026-11-14T09:30:00Z",
  "reason": null
}
```

- 只有 `admin` 能触发，非 admin 403 `forbidden`。
- 不存在 404 `connector_not_found`；属于其他租户且调用方不是 admin 403 `tenant_forbidden`。
- 未配置存储 404 `connectors_not_configured`；存储不可达 503 `connector_store_unavailable`。
- 探测从控制台进程发出，`GET` 连接器的第一个路径前缀，不带凭据，不跟随重定向，超时取连接器配置与 5 秒的较小值，不读取响应体。
- `status` 取 `healthy`、`unauthorized`、`not_found`、`redirect`、`server_error`、`unexpected_status`、`unreachable`。`reason` 只在 `unreachable` 时取 `timeout` 或 `connect_error`。
- 不写审计，不改连接器记录。

## `GET /api/peers?tenant=<name>` -> `[{"peer": PeerIdentity, "grants": [PeerGrant]}]`

只读 peer 与其授权。按 `peer_id` 排序。

- 由 `console --peer-dir DIR`（文件）或 `--peer-db URL`（Postgres）提供；都未配置返回 404 `peers_not_configured`。
- 非 `admin` 只返回自己租户的 peer；`admin` 可按 `tenant` 取一个租户，缺省返回全部。
- 存储不可达返回 503 `peer_store_unavailable`。

## `POST /api/peers` -> `PeerIdentity`

```json
{"peer_id": "peer-a", "tenant": "acme", "subject": "sub-1", "kind": "service", "roles": []}
```

- 只有 `admin` 能写，非 admin 403 `forbidden`。
- 请求体不是对象 400 `invalid_request`；校验失败 400 `invalid_peer`。
- 新 peer 返回 200；已存在且字段一致幂等返回 200；已存在但改 `tenant` 返回 409 `peer_tenant_immutable`。
- 成功写 `peer.register` 审计，`target` 是 peer id，tenant 是调用方租户。

## `POST /api/peers/{peer_id}/disable` -> `PeerIdentity`

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 不存在 404 `peer_not_found`；重复停用幂等返回 200。
- 成功写 `peer.disable` 审计。

## `POST /api/peers/{peer_id}/grants` -> `PeerGrant`

```json
{"agent_id": "bot", "actions": ["read", "invoke"]}
```

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- peer 不存在 404 `peer_not_found`；`actions` 为空或含未知值 400 `invalid_grant`。
- 授权记录的 `tenant` 取 peer 的租户，请求体不接受 `tenant`。
- 写入按 `(peer_id, agent_id)` 覆盖，成功返回 200 并写 `peer.grant` 审计，`target` 是 `<peer_id>/<agent_id>`。

## `DELETE /api/peers/{peer_id}/grants/{agent_id}` -> `{"revoked": bool}`

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- peer 不存在 404 `peer_not_found`；授权不存在返回 `{"revoked": false}` 与 200。
- 实际删除时写 `peer.revoke` 审计。

## `GET /api/remote-agents?tenant=<name>` -> `[RemoteAgent]`

远端 A2A agent 的目录记录（ADR-0015）。按 `remote_id` 排序。

```json
{
  "remote_id": "crm-bot",
  "tenant": "acme",
  "peer_id": "crm",
  "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
  "credential_ref": "secret://crm/token",
  "label": "CRM bot",
  "card_digest": "sha256:<64 hex>",
  "observed_digest": null,
  "checked_at": "2026-11-14T09:30:00Z",
  "status": "pinned",
  "enabled": true
}
```

- 由 `console --peer-dir DIR` 或 `--peer-db URL` 提供；未配置返回 404 `remote_agents_not_configured`。
- 非 `admin` 只返回自己租户的记录；`admin` 可按 `tenant` 过滤，缺省返回全部。
- 存储不可达返回 503 `remote_agent_store_unavailable`。

## `POST /api/remote-agents` -> `RemoteAgent`

```json
{"remote_id": "crm-bot", "tenant": "acme", "peer_id": "crm",
 "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
 "credential_ref": "secret://crm/token", "label": "CRM bot"}
```

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 请求体非法 400 `invalid_request`；字段校验失败 400 `invalid_remote_agent`。
- peer 不存在或未启用 404 `peer_not_found`；记录租户与 peer 租户不一致 400 `tenant_mismatch`。
- 用 `credential_ref` 经 `SecretProvider` 解析凭据拉取 card，要求 card 的 `name` 等于 `remote_id`。
- 拉取失败 502 `card_unreachable`、502 `card_unauthorized`、502 `card_too_large` 或 502 `card_invalid`；名称不符 400 `card_name_mismatch`；凭据解析失败 503 `secret_unavailable`。
- 成功返回 200，`status="pinned"`，`card_digest` 是 card 原始字节的 sha256，`observed_digest` 为空。已存在的 `remote_id` 重新注册即重新批准；已存在记录的 `tenant` 不可改，返回 409 `remote_agent_tenant_immutable`。
- 写 `remote_agent.register` 审计，`target` 是 `remote_id`。

## `POST /api/remote-agents/{remote_id}/refresh` -> `RemoteAgent`

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 不存在 404 `remote_agent_not_found`。
- 重新拉取并比较摘要。一致记 `pinned` 并清空 `observed_digest`；不一致保留 `card_digest`，把新摘要写入 `observed_digest` 并记 `changed`；拉取或凭据失败保留两个摘要，记 `unreachable`。三种情况都更新 `checked_at`。
- 写 `remote_agent.refresh` 审计。

## `POST /api/remote-agents/{remote_id}/disable` -> `RemoteAgent`

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 不存在 404 `remote_agent_not_found`；重复停用幂等。
- 写 `remote_agent.disable` 审计。

## `GET /api/tool-grants?tenant=<name>&status=<status>` -> `[ToolGrantRequest]`

列出工具临时授权请求，按 `requested_at` 倒序。`status` 取 `pending`、`approved`、`denied`、`expired`、`cancelled`，其他值 400 `invalid_status`。

- 未配置授权存储返回 404 `tool_grants_not_configured`。
- `tenant` 缺失时用当前 principal 的租户；非 `admin` 跨租户 403 `tenant_forbidden`。
- 存储不可达返回 503 `grant_store_unavailable`。

## `GET /api/tool-grants/usage?tenant=<name>` -> `[ToolUsage]`

按工具汇总最近的 `tool.call` 审计事件。`temporary` 是被临时授权放行的次数（`policy_version=grants-v2`）。

```json
{"tool_id": "crm.read", "allowed": 3, "denied": 1, "temporary": 2}
```

- 事件来源与控制台审计面板相同（共享审计或进程缓冲），上限 1000 条。
- 非 `admin` 只能看自己的租户；审计服务不可用返回 502 `audit_unavailable`。
- Grants 面板对已批准且 24 小时内到期的请求显示 expiring 徽标。

## `POST /api/tool-grants` -> `ToolGrantRequest`

```json
{
  "tenant": "acme",
  "agent_id": "support-bot",
  "version": "1.0.0",
  "digest": "sha256:...",
  "tool_id": "crm.read",
  "data_classes": ["internal"],
  "reason": "temporary support access",
  "expires_hours": 24
}
```

- 版本必须已发布且 `digest` 与记录一致，否则 404 `not_found`；退役版本 409 `version_retired`。
- `expires_hours` 默认 24，范围 1 到 168，否则 400 `invalid_request`；`reason` 不能为空。
- 申请人取 principal 的 `subject`，状态 `pending`。
- 成功 201。写 `tool_grant.request` 审计。
- 非 `admin` 跨租户 403 `tenant_forbidden`；未配置存储 404 `tool_grants_not_configured`；存储不可达 503 `grant_store_unavailable`。

## `POST /api/tool-grants/{request_id}/decide` -> `ToolGrantRequest`

```json
{"approved": true, "reason": "ok"}
```

- 只有 `admin` 能审批，非 admin 返回 403 `forbidden`。
- 请求不存在 404 `grant_not_found`；终态 409 `grant_already_decided`；待审但已过期 410 `grant_expired`。
- 成功 200，写 `tool_grant.decide` 审计。

## `POST /api/registry/unload` -> `{"name", "unloaded"}`

卸载一个按需加载的 agent，释放运行时与聊天目标。启动时加载的 agent 不能卸载。

```json
{"name": "support-bot"}
```

- 成功 200 `{"name": "support-bot", "unloaded": true}`，写 `agent.unload` 审计。
- agent 不存在 404 `not_found`；启动时加载的 agent 409 `not_unloadable`；非 `admin` 加载其他租户的版本 403 `tenant_forbidden`。
- 正在进行的运行持有自己的运行时引用，不会被中断；卸载只影响后续加载与聊天选择。
- 市场页对按需加载的版本提供 Unload 按钮；Open chat 遇到 `name_conflict` 时先卸载再重试一次，实现同位置换版本。

## `GET /api/runs?limit=50` -> `[RunSummary]`

从审计缓冲或审计服务读出的事件按 `run_id` 聚合，按最后事件时间倒序。`limit` 夹在 1 到 200。配置了 `--audit-url` 时服务不可用返回 502 `audit_unavailable`。

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

列出该 agent 在当前主体下的会话，按最后更新时间倒序。开启 `--session-tenant-scope` 时主体键是 `<tenant>:<subject>`，否则是 `<subject>`。

```json
{"session_id": "s1", "last_update_time": "2026-11-12T10:00:00Z"}
```

- 不返回 `state` 和 `events`。
- 只列当前 principal `subject` 的会话。
- 未知 agent 返回 400 `unknown_agent`。
