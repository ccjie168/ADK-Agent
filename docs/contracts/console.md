# Console HTTP 契约

`GET /`、`GET /healthz`、`GET /auth/config`、`GET /auth/callback` 和 `POST /auth/token` 开放。其余 `/api/*` 需要 `Authorization: Bearer <token>`。

鉴权有两种模式。静态 token 模式比较启动时给的单一 token。OIDC 模式验证 JWT，把解析出的 `Principal` 挂到请求上。OIDC 模式下 token 不合法返回 401 `{"error":"unauthorized"}`，签发方不可达返回 503 `{"error":"identity_unavailable"}`。

OIDC 模式下，会话按 principal 的 `subject` 隔离。非 `admin` 身份只能读自己租户的注册表，越权返回 403 `{"error":"tenant_forbidden"}`。策略更新仍由 `policy.update` 的 RBAC 判定，角色来自 token。

## `GET /api/me` -> 能力清单

```json
{
  "tenant": "acme",
  "subject": "console_user",
  "roles": ["operator"],
  "capabilities": ["approvals.decide", "approvals.read", "audit.read", "chat.run"]
}
```

- 鉴权与其他 `/api/*` 相同，缺少或错误的 token 返回 401 `{"error":"unauthorized"}`。
- `capabilities` 由服务端按角色映射计算，映射只在一处定义。同一主体有多个角色时取并集。未知角色只得到基础能力。
- 基础能力是 `chat.run`、`runs.read`、`sessions.read`。
- 读接口按消费它的面板检查能力：审计 `audit.read`，策略 `policy.read`，注册表与评测 `registry.read`，工具目录 `tools.read`，工具授权 `grants.read`，连接器、连接器申请与凭据 `connectors.read`，对端与远程目录 `peers.read`。
- 写接口按操作检查能力：注册表按需加载与卸载 `registry.load`，工具授权申请 `grants.request`。写接口的能力检查先于请求体解析、配置 404 与租户检查。
- 运行、计划、trace、会话与聊天接口检查基础能力 `runs.read`、`sessions.read`、`chat.run`。这些能力按现有角色表对每个主体都为真，检查用于未来增加受限角色时的防御；租户可见性仍由既有的租户过滤决定。带显式租户参数的读接口保持租户检查先于能力检查。
- `operator`、`ops`、`approver` 加 `approvals.read`、`approvals.decide`、`grants.read`、`grants.decide`、`audit.read`、`connectors.read`、`peers.read`、`registry.read`、`policy.read`。
- `publisher`、`developer` 加 `registry.read`、`registry.publish`、`registry.load`、`eval.read`、`tools.read`、`lifecycle.read`、`grants.read`、`grants.request`。
- 其余管理能力只由 `admin` 得到，包括 `connectors.manage`、`peers.manage`、`policy.write`、`ops.status`。`admin` 隐含全部能力。
- 控制台的前端只按 `capabilities` 显示导航与按钮。每个接口仍各自授权，403 语义不变。能力清单不能替代接口检查。
- 能力清单获取失败时控制台保持现有布局，不阻断使用。

## 浏览器登录（PKCE）

配置文件的 `browser` 段（见 `oidc_config.schema.json`）存在时，控制台启用授权码加 PKCE（S256）登录。浏览器用 `/auth/config` 拿公开参数，跳转到授权端点，回调页用 code 和 sessionStorage 里的 verifier 换 token，再把 token 当作后续 `/api/*` 的 bearer token。`token_endpoint` 与 `client_secret_env` 不下发浏览器。

- `GET /auth/config`：没有浏览器配置时返回 `{"enabled": false}`；否则返回 `{enabled: true, client_id, authorization_endpoint, redirect_uri, scopes}`。
- `GET /auth/callback`：返回控制台 HTML，不校验查询参数。
- `POST /auth/token`：请求 `{code, code_verifier, redirect_uri}`。`redirect_uri` 必须与配置一致，verifier 长度 43 到 128。服务端以 `grant_type=authorization_code` 调 token endpoint；成功返回 `{access_token, token_type, expires_in?}`。字段缺失或不是非空字符串返回 400 `{"error":"invalid_request"}`；兑换失败返回 401 `{"error":"oidc_login_failed"}`，不返回上游错误细节；没有配置登录返回 404 `{"error":"oidc_not_configured"}`。

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

需要 `chat.run` 能力，缺少返回 403 `forbidden`，先于请求体解析。

租户配额用尽时返回 429 `{"error":"quota_exceeded"}`，并写一条 `agent.run` 的 `denied` 审计，`error_code` 是 `quota_exceeded`。配额在模型调用前检查，超限的请求不会触发模型。配额后端不可用返回 503 `{"error":"quota_unavailable"}`。

可选请求头 `X-Trace-Id`，必须匹配 `^[A-Za-z0-9._-]{1,128}$`。没有合法值时读 `traceparent` 的 trace-id，规则见 `tracing.md`。两者都没有时自动生成。

## `POST /api/chat/stream`

请求同 `/api/chat`。响应 `text/event-stream`。同样需要 `chat.run` 能力，缺少返回 403 `forbidden`，先于请求体解析。

- `event: progress`，数据是 `ProgressEvent`（见 `progress_event.schema.json`）。
- `event: done`，数据是 `{session_id, reply, run_id, trace_id, dropped}`，`dropped` 总是存在。
- `event: error`，数据是 `{error}`，文案固定。丢弃过进度时额外带 `dropped`（正整数）。配额用尽时是 `{"error":"quota_exceeded"}`。
- 每条流最多缓冲 `<sse-queue-size>` 条 `progress`。客户端读得慢时丢弃最旧的 `progress`，保留最新的和终结事件。`dropped` 是被丢掉的条数。
- `progress` 事件可能因慢客户端缺失，终结事件 `done` / `error` 不会丢。
- 鉴权和策略检查在建流前完成，拒绝返回普通 JSON 错误。

## `GET /api/approvals` -> `[ApprovalRequest]`

返回待决的人工审批请求，按 `requested_at` 正序。结构见 `approval_request.schema.json`。

- 已过期的请求不返回。`expires_at` 是有效截止时间。请求自带时原样返回；没有时由收件箱用 `requested_at` 加配置的 TTL 推算；两者都没有时为 `null`。
- 需要 `approvals.read` 能力，缺少返回 403 `forbidden`，先于任何存储访问与配置检查。
- 未配置审批目录或审批数据库时返回 404 `approvals_not_configured`。
- 非 `admin` 身份只看到自己租户的请求。
- 请求里的 `input` 是待审内容，只在这里返回给有权限的调用方。
- 收件箱后端在启动时确定。`--approval-db` 或 `$APPROVAL_DATABASE_URL` 使用 Postgres；`--approval-dir` 或 `$ADK_APPROVAL_DIR` 使用目录。显式 flag 优先于环境变量，两个显式 flag 同时给出时控制台退出 1；只有环境变量时 `APPROVAL_DATABASE_URL` 优先。
- 数据库不可达时返回 503 `approval_unavailable`，不返回空列表。

## `POST /api/approvals/{request_id}`

请求：`{approved, reason?}`
响应：`ApprovalDecision`，结构见 `approval_decision.schema.json`。`approver` 是当前 principal 的 `subject`，`decided_at` 由服务端生成。

- 需要 `approvals.decide` 能力，缺少返回 403 `forbidden`，先于请求体与 id 校验。
- 请求 id 必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则 400 `unsafe_request_id`。
- `approved` 缺失或不是布尔返回 400 `invalid decision`。
- 请求不存在返回 404 `approval_not_found`。
- 已决请求返回 409 `approval_already_decided`，决定不可改写。
- 已过期且未决的请求返回 410 `approval_expired`。
- 非 `admin` 身份决定其他租户的请求返回 403 `tenant_forbidden`。
- 配置了 `--policy` 时按 `approval.decide:<agent_id>` 判定，拒绝返回 403 `policy_denied`。
- 每次成功决定写一条 `approval.decide` 审计，`target` 是请求 id，`approver` 是审批人，`status` 是 `ok` 或 `denied`。审计不含待审 `input`。
- 未配置审批目录或审批数据库时返回 404 `approvals_not_configured`。
- 数据库不可达时返回 503 `approval_unavailable`。

## `GET /api/approvals/history?limit=50&status=<status>` -> `[ApprovalHistoryEntry]`

已决与已过期的审批记录，按终结时间倒序。`status` 取 `approved`、`denied`、`expired` 或 `cancelled`，其他值返回 400 `invalid_status`。`limit` 夹在 1 到 200。

```json
{
  "request": {"request_id": "r1", "...": "ApprovalRequest"},
  "decision": {"request_id": "r1", "approved": true, "approver": "alice", "...": "ApprovalDecision"},
  "status": "approved",
  "archived": false,
  "terminal_at": "2026-11-16T10:00:00Z"
}
```

- 需要 `approvals.read` 能力，缺少返回 403 `forbidden`，先于 `status` 校验与存储访问。
- 未配置审批存储返回 404 `approvals_not_configured`；存储不可达返回 503 `approval_unavailable`。
- 非 `admin` 只返回自己租户的记录，租户取 `request.principal.tenant`。`admin` 可看全部租户。
- 包含已归档记录，`archived` 为 true。`terminal_at` 取 `decision.decided_at`；过期记录取 `expires_at`；都没有时取 `requested_at`。
- 没有决定且未过期的待决请求不出现在历史里。
- 读取历史不写审计。

## `GET /api/plans?limit=50` -> `[PlanSummary]`

从当前进程的审计缓冲按 `trace_id` 聚合 `orchestration.run` 事件，按最后事件时间倒序。`limit` 夹在 1 到 200。需要 `runs.read` 能力，缺少返回 403 `forbidden`。

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

## `GET /api/traces/{trace_id}` -> `{trace_id, root, total_ms, error}`

根是最后一条 `agent.run` 或 `orchestration.run` 事件，`children` 是同一 trace 的其余事件。
需要 `runs.read` 能力，缺少返回 403 `forbidden`，先于 `trace_id` 格式检查。
非 `admin` 身份只能看到自己租户的事件，别的租户的 trace 视为找不到。
找不到根时 `root` 为 `null`，`error` 为 `trace_not_found`。配置了 `--audit-url` 时服务不可用返回 502 `audit_unavailable`。`trace_id` 必须匹配
`^[A-Za-z0-9._-]{1,128}$`。

每个节点在原有字段外带两个瀑布图字段：

- `start_offset_ms`：相对根事件时间戳的起点，整数毫秒；早于根的节点夹为 0。
- `duration_ms`：`latency_ms` 的副本，缺失时为 0。

顶层 `total_ms` 是所有节点 `start_offset_ms + duration_ms` 的最大值。全部节点都没有延迟时，取最晚起点的偏移。

```json
{
  "trace_id": "trace-1",
  "error": null,
  "total_ms": 50,
  "root": {
    "id": "probe@dev", "kind": "agent", "status": "ok",
    "start_offset_ms": 0, "duration_ms": 50,
    "latency_ms": 50, "cost_usd": 0.001, "error_code": null,
    "timestamp": "2026-01-01T00:00:00Z",
    "children": [
      {
        "id": "litellm:deepseek", "kind": "model", "status": "ok",
        "start_offset_ms": 10, "duration_ms": 20,
        "latency_ms": 20, "cost_usd": 0.001, "error_code": null,
        "timestamp": "2026-01-01T00:00:00.010000Z"
      }
    ]
  }
}
```

节点还带下列审计字段，供运行详情下钻使用。事件没有值时可空字段为 `null`。

- `event_id`、`run_id`、`action`、`target`、`tenant`
- `principal`：`{subject, kind}`
- `agent`：`{id, version}`
- `approver`、`args_hash`、`result_hash`、`policy_decision_id`、`policy_version`
- `data_classes`：字符串数组
- `tokens`、`egress`

这些字段只来自审计事件，不包含 prompt、completion 或工具参数原文。

## `GET /api/audit?limit=50` -> `[AuditEvent]`

`limit` 上限 200。事件按时间正序，最多返回最近 200 条。需要 `audit.read` 能力，缺少返回 403 `forbidden`。非 `admin` 身份只返回自己租户的事件。聊天面板的 Recent audit 区块同样按 `audit.read` 隐藏。配置了 `--audit-url` 时从审计服务读取，服务不可用返回 502 `audit_unavailable`。

事件结构见 `audit_event.schema.json`。

## `GET /api/policy` -> `AccessPolicy`

返回当前访问策略，结构见 `access_policy.schema.json`。仅在配置了 `--policy` 时存在。

- 需要 `policy.read` 能力，缺少返回 403 `forbidden`。
- 未配置策略文件时返回 404。
- `PUT /api/policy` 不走能力清单，仍由 `policy.update` 的 RBAC 判定；拒绝返回 403 `policy_denied`。

## `GET /api/tenants` -> `[str]`

返回注册表里已发布租户的目录名，按字典序。注册表根目录不存在时返回空数组。非 `admin` 身份只返回自己的租户名。

未配置注册表时返回 404 `{"error":"registry_not_configured"}`。

## `GET /api/registry?tenant=<name>` -> `[RegistryEntry]`

返回该租户的已发布版本与远端目录记录。`tenant` 缺失时用当前 principal 的租户。需要 `registry.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。本地条目按 `(id, version)` 排序，远端条目按 `id` 排序；混合视图按 `id` 排序，同 `id` 时 `local` 在前。

```json
{
  "tenant": "team-a",
  "id": "support-bot",
  "source": "local",
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

远端条目（ADR-0015）形状不同，`source` 为 `remote`：

```json
{
  "tenant": "team-a",
  "id": "crm-bot",
  "source": "remote",
  "peer_id": "crm",
  "label": "CRM bot",
  "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
  "enabled": true,
  "trust": {
    "status": "pinned",
    "card_digest": "sha256:...",
    "observed_digest": null,
    "checked_at": "2026-11-14T09:30:00Z"
  }
}
```

远端条目没有 `version`、`digest`、`published_at`、`manifest`、`artifact` 与 `lifecycle`。`trust.status` 为 `pinned`、`changed` 或 `unreachable`；后两种仍返回，由界面显示警告。停用的远端条目也返回，`enabled` 为 `false`。

`lifecycle` 是 ADR-0010 的状态；没有状态行时是默认的 `published`。`artifact` 为 `null` 表示该版本没有工件。`status` 是 `verified`、`untrusted`、`unknown`（控制台没有配置可信密钥）或 `unsigned`（工件没有签名）。

- 非法租户返回 400 `unsafe_tenant`。
- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 记录损坏返回 500 `registry_corrupt`，响应不含文件路径。
- 生命周期存储不可用返回 503 `lifecycle_unavailable`。
- 远端存储不可用返回 503 `remote_agent_store_unavailable`。
- 注册表与远端目录都未配置返回 404 `registry_not_configured`；只配置其一则只返回该来源的条目。

## `GET /api/registry/{tenant}/{id}/{version}/eval` -> `EvalReport`

返回该版本的评测报告，结构见 `eval_report.schema.json`。

- 需要 `registry.read` 能力，缺少返回 403 `forbidden`。
- 非 `admin` 身份请求其他租户返回 403 `tenant_forbidden`。
- 没有报告返回 404 `eval_report_not_found`。
- 非法路径分量返回 400 `unsafe_tenant`。
- 未配置注册表返回 404 `registry_not_configured`。

## `POST /api/registry/load` -> `{"name", "version", "loaded"}`

按需把一个已发布版本加载成聊天目标。`in_process` 记录在控制台进程内执行；
`sandboxed` 记录返回沙箱代理，每次调用起一个子进程，见 `sandbox.md`。

```json
{"tenant": "team-a", "id": "support-bot", "version": "1.0.0"}
```

成功返回 200 `{"name": "support-bot", "version": "1.0.0", "loaded": true}`。同名 agent 已在控制台加载时返回 200 且 `loaded=false`，不切换版本。

- 需要 `registry.load` 能力，缺少返回 403 `forbidden`，先于请求体解析与配置检查。
- 需要注册表、工件存储和可信公钥。缺注册表返回 404 `registry_not_configured`，缺存储返回 503 `artifact_store_unavailable`，缺公钥返回 503 `artifact_trust_unavailable`。
- 请求体不是 JSON 或字段不合法返回 400 `invalid_request`。
- 非 `admin` 身份加载其他租户返回 403 `tenant_forbidden`。
- 版本不存在返回 404 `not_found`。
- 该版本没有工件返回 409 `artifact_missing`；签名缺失或不可信返回 409 `artifact_untrusted`。
- 加载前比较工件内 `manifest.json` 与记录 manifest；不一致或字节缺失返回 500 `load_failed`。
- 记录声明 `sandboxed` 而控制台没有 agent 沙箱后端时返回 409 `sandbox_unavailable`（ADR-0024）。
- 记录声明 `sandboxed` 且声明了工具授权、而进程沙箱没有工具执行器时返回 409 `tool_mediation_unavailable`。
- 同名 agent 已按另一版本按需加载返回 409 `name_conflict`。
- 版本已退役返回 409 `version_retired`；`deprecated` 版本仍可加载。
- 已加载数量达到 `--max-loaded-agents` 返回 409 `load_limit`。
- 工件无法加载成同名 ADK agent 返回 500 `load_failed`。
- 生命周期存储不可用返回 503 `lifecycle_unavailable`。
- 成功加载写一条 `agent.load` 审计，`status=ok`，`target` 是 agent 名，`tenant` 是调用方的租户（审计事件要求租户等于 principal 的租户）。

## `GET /api/tools?tenant=<name>` -> `[ToolEntry]`

只读工具目录。每个条目附带该租户已发布版本里引用它的 agent。需要 `tools.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。

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

- 需要 `connectors.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
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
- 配置了凭据存储时，`auth_ref` 是两段租户引用且没有同租户启用绑定时 400 `credential_unbound`；全局连接器不得使用两段租户引用，同样返回 400 `credential_unbound`。
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

## `GET /api/credentials?tenant=<name>` -> `[CredentialBinding]`

只读凭据引用清单，按 `credential_id` 排序。记录只含元数据，没有密钥值。形状与存储见 `credentials.md`。

- 需要 `connectors.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
- 由 `console --credentials-dir DIR` 或 `--credential-db URL`（都未给时读 `CREDENTIAL_DATABASE_URL`）提供；未配置返回 404 `credentials_not_configured`。
- `tenant` 缺失时用当前 principal 的租户；非 `admin` 跨租户 403 `tenant_forbidden`。
- 存储不可达返回 503 `credential_store_unavailable`。

## `POST /api/credentials` -> `CredentialBinding`

- 只有 `admin` 能登记，非 admin 403 `forbidden`。
- 请求体不是 JSON 或不是对象 400 `invalid_request`；`CredentialBinding` 校验失败（含跨租户引用）400 `invalid_credential`。
- `created_by` 与 `created_at` 由服务端覆盖为调用主体与当前时间。
- 同键同定义重发 201，幂等；不同定义 409 `credential_conflict`。
- 成功 201，写 `credential.register` 审计，`target` 是 `<tenant>/<credential_id>`。
- 未配置存储 404 `credentials_not_configured`；存储不可达 503 `credential_store_unavailable`。

## `POST /api/credentials/{credential_id}/disable?tenant=<name>` -> `CredentialBinding`

- 只有 `admin` 能停用，非 admin 403 `forbidden`。
- `tenant` 缺失时用当前 principal 的租户；给了其他租户按该租户定位。
- 不存在 404 `credential_not_found`。
- 成功 200，重复停用幂等，写 `credential.disable` 审计。
- 未配置存储 404 `credentials_not_configured`；存储不可达 503 `credential_store_unavailable`。

## 连接器申请

形状与存储见 `connector_requests.md`。

`GET /api/connector-requests?tenant=<name>&status=<status>` -> `[ConnectorRequest]`：按 `requested_at` 倒序。需要 `connectors.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。`tenant` 缺失时用当前 principal 的租户；非 `admin` 跨租户 403 `tenant_forbidden`；`status` 不在 `pending`、`approved`、`denied` 中 400 `invalid_status`。由 `console --connector-requests-dir DIR` 或 `--connector-request-db URL`（都未给时读 `CONNECTOR_REQUEST_DATABASE_URL`）提供；未配置 404 `connector_requests_not_configured`；存储失败 503 `connector_request_store_unavailable`。

`POST /api/connector-requests` -> `ConnectorRequest`：请求 `{spec, reason}`，任何已认证主体可提交。服务端取调用主体作为 `tenant` 与 `requested_by`，生成 `request_id`；`spec.tenant` 必须等于调用方租户，否则 400 `invalid_connector_request`。成功 201，写 `connector.request` 审计。

`POST /api/connector-requests/{request_id}/decide` -> `ConnectorRequest`：仅 `admin`。请求 `{approved, reason}`。

- 拒绝把状态改为 denied，不写连接器存储，写 `connector.request.decide` 审计，状态 `denied`。
- 批准先查凭据绑定，未绑定 400 `credential_unbound`；再登记连接器，冲突 409 `connector_conflict`；登记成功后标记 approved，写 `registered_connector`，并写 `connector.register` 与 `connector.request.decide` 审计。
- 不存在 404 `connector_request_not_found`；已决定 409 `connector_request_already_decided`。

## `GET /api/peers?tenant=<name>` -> `[{"peer": PeerIdentity, "grants": [PeerGrant]}]`

只读 peer 与其授权。按 `peer_id` 排序。

- 需要 `peers.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
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
  "credential_ref": "secret://acme/token",
  "label": "CRM bot",
  "card_digest": "sha256:<64 hex>",
  "observed_digest": null,
  "checked_at": "2026-11-14T09:30:00Z",
  "status": "pinned",
  "enabled": true
}
```

- 需要 `peers.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
- 由 `console --peer-dir DIR` 或 `--peer-db URL` 提供；未配置返回 404 `remote_agents_not_configured`。
- 非 `admin` 只返回自己租户的记录；`admin` 可按 `tenant` 过滤，缺省返回全部。
- 存储不可达返回 503 `remote_agent_store_unavailable`。

## `POST /api/remote-agents` -> `RemoteAgent`

```json
{"remote_id": "crm-bot", "tenant": "acme", "peer_id": "crm",
 "agent_card_url": "https://crm.example.com/.well-known/agent-card.json",
 "credential_ref": "secret://acme/token", "label": "CRM bot"}
```

- 只有 `admin` 能写，非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 请求体非法 400 `invalid_request`；字段校验失败 400 `invalid_remote_agent`。
- peer 不存在或未启用 404 `peer_not_found`；记录租户与 peer 租户不一致 400 `tenant_mismatch`。
- 用 `credential_ref` 经 `SecretProvider` 解析凭据拉取 card，要求 card 的 `name` 等于 `remote_id`。引用是两段 `secret://tenant/name` 时首段必须等于记录租户，否则按解析失败处理。
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

- 需要 `grants.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
- 未配置授权存储返回 404 `tool_grants_not_configured`。
- `tenant` 缺失时用当前 principal 的租户；非 `admin` 跨租户 403 `tenant_forbidden`。
- 存储不可达返回 503 `grant_store_unavailable`。

## `GET /api/tool-grants/usage?tenant=<name>` -> `[ToolUsage]`

按工具汇总最近的 `tool.call` 审计事件。`temporary` 是被临时授权放行的次数（`policy_version=grants-v2`）。

```json
{"tool_id": "crm.read", "allowed": 3, "denied": 1, "temporary": 2}
```

- 需要 `grants.read` 能力，缺少返回 403 `forbidden`；租户参数检查先于能力检查。
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

- 需要 `grants.request` 能力，缺少返回 403 `forbidden`，先于请求体解析与租户检查；工具授权面板的 Request 按钮按同一能力显示。
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

- 需要 `registry.load` 能力，缺少返回 403 `forbidden`，先于请求体解析。
- 成功 200 `{"name": "support-bot", "unloaded": true}`，写 `agent.unload` 审计。
- agent 不存在 404 `not_found`；启动时加载的 agent 409 `not_unloadable`；非 `admin` 加载其他租户的版本 403 `tenant_forbidden`。
- 正在进行的运行持有自己的运行时引用，不会被中断；卸载只影响后续加载与聊天选择。
- 市场页对按需加载的版本提供 Unload 按钮；Open chat 遇到 `name_conflict` 时先卸载再重试一次，实现同位置换版本。

## `GET /api/runs?limit=50` -> `[RunSummary]`

从审计缓冲或审计服务读出的事件按 `run_id` 聚合，按最后事件时间倒序。`limit` 夹在 1 到 200。需要 `runs.read` 能力，缺少返回 403 `forbidden`。配置了 `--audit-url` 时服务不可用返回 502 `audit_unavailable`。

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

列出该 agent 在当前主体下的会话，按最后更新时间倒序。需要 `sessions.read` 能力，缺少返回 403 `forbidden`，先于 `agent` 参数检查。开启 `--session-tenant-scope` 时主体键是 `<tenant>:<subject>`，否则是 `<subject>`。

```json
{"session_id": "s1", "last_update_time": "2026-11-12T10:00:00Z"}
```

- 不返回 `state` 和 `events`。
- 只列当前 principal `subject` 的会话。
- 未知 agent 返回 400 `unknown_agent`。
