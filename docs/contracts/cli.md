# CLI 契约

## `adk-agent validate <path>`

解析并校验 `AgentManifest` JSON。

- 成功：stdout 输出 `tenant/id@version sha256:<digest>`，退出 0。
- 失败：stderr 输出 `invalid manifest: <原因>`，退出 1。
- 未知字段、非法 `id` / `version` / `tenant`、缺失必填字段都算失败。

## `adk-agent publish <path> [--registry DIR] [--eval-report FILE]`

校验 manifest，跑评测门禁，计算 digest，写入注册表。

- manifest 声明 `eval_suite` 时必须给 `--eval-report`，且报告的 `suite_id`、`version` 一致，`score` 不低于 `pass_threshold`。否则退出 1，不写注册表。
- 成功：stdout 输出 `published tenant/id@version sha256:<digest>`，退出 0。
- 重复发布相同内容：幂等成功，返回已存记录。
- 同版本不同内容：stderr 输出 `publish failed: <原因>`，退出 1。
- 通过门禁的报告写到 `<registry>/<tenant>/<id>/<version>.eval.json`。相同报告重复发布幂等，不同报告退出 1。
- 报告写失败退出 1，版本可能已写入；重新发布同一 manifest 会把报告补上。
- 默认注册表目录是 `$ADK_REGISTRY_DIR`，否则 `./registry`。
- 存储布局是 `<registry>/<tenant>/<id>/<version>.json`。租户目录来自 manifest，不受调用方控制。

## `adk-agent eval <suite> --agents FILE [--out FILE]`

跑一个 `EvalSuiteSpec` 并输出 `EvalReport`。

- `suite.agent` 必须在 `--agents` 的映射里，否则退出 1。
- 用例判定是 `exact` 或 `contains`，不做模型裁判。
- 调用抛异常的用例记为失败，`error` 是异常类名。
- 给了 `--out` 写入文件并输出 `wrote <path>`，否则报告 JSON 写 stdout。

## `adk-agent new <name> [--template minimal] [--tenant TENANT]`

生成一个模板项目。

- `name` 和 `tenant` 都必须匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*$`。
- `--tenant` 默认 `local`，写入生成的 `manifest.json`。
- 生成 `agent.py`、`manifest.json`、`README.md`、`tests/test_agent.py`。
- 生成的 `manifest.json` 必须通过 `AgentManifest` 校验。
- `agent.py` 已存在时退出 1。
- 未知模板退出 1。
- 成功时逐行输出 `created <path>`，退出 0。

## `adk-agent serve-model-gateway [--provider NAME]... [--vllm-url URL] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--oidc-config FILE]`

把模型网关作为独立服务运行。

- 默认 provider 是 `litellm`。`--provider vllm` 需要 `--vllm-url` 或 `$VLLM_BASE_URL`。
- 只有 `/healthz` 开放。`POST /v1/complete` 需要 bearer token，非回环地址没 token 拒绝启动。
- 策略拒绝返回 403 `{"error":"model_denied"}`，provider 失败返回 502 `{"error":"model_call_failed"}`。
- `GET /metrics` 需要 token，指标见 `metrics.md`。
- 给了 `--audit-file` 时每个 `model.call` 事件追加一行 JSON。
- 给了 `--audit-url` 时每个事件 `POST` 到 `<url>/v1/events`，期望 202。非 202 或连不上抛 `AuditSinkUnavailable`，当前请求以 502 结束。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。
- 审计 token 从 `--audit-token-env` 指定的环境变量读，默认 `ADK_AUDIT_AUTH_TOKEN`。非回环 URL 没有 token 拒绝启动，退出 1。
- 给了 `--oidc-config` 就改用 OIDC 鉴权，忽略 `--auth-token-env`。和 `--allow-unauthenticated` 互斥，同时给退出 1。
- OIDC 模式下，请求体的 `invocation.principal` 的 `tenant` 和 `subject` 必须与 token 一致，否则返回 403 `principal_mismatch`。角色、kind、attributes 以 token 为准。

## `adk-agent serve-audit --out FILE [--oidc-config FILE]`

把审计管线作为独立服务运行。

- 只有 `/healthz` 开放。`POST /v1/events` 需要 bearer token，非回环地址没 token 拒绝启动。
- 成功返回 202 `{"hash":"..."}`。写入失败返回 502 `{"error":"audit_write_failed"}`。
- `FILE` 每行一条 `AuditRecord`，同租户串成哈希链，每租户首条 `prev_hash` 为空串。
- 给了 `--oidc-config` 就改用 OIDC 鉴权，忽略 `--auth-token-env`。和 `--allow-unauthenticated` 互斥。
- OIDC 模式下，事件的 `tenant` 和 `principal.subject` 必须与 token 一致，否则返回 403 `principal_mismatch`。角色、kind、attributes 以 token 为准。

## `adk-agent approvals prune --dir DIR --older-than SECONDS [--delete]`

归档或删除已经终结、且超过保留期的审批记录。

- `--dir` 默认 `$ADK_APPROVAL_DIR`，两者都没有时退出 1。
- `--older-than` 必须是大于 0 的秒数，否则退出 1。
- 终结时间取决定的 `decided_at`；没有决定但已过期的请求取 `expires_at`。没有决定且未过期的请求永远保留。
- 默认把 `<id>.request.json` 和 `<id>.decision.json` 移到 `<dir>/archive/`。归档目录里已有同名文件时跳过该条，源文件保留。
- `--delete` 改为删除，不归档。
- 成功输出 `archived N requests` 或 `deleted N requests`，退出 0。
- 这个命令不写审计事件。

## `adk-agent verify-audit FILE`

逐条重算审计链。

- 通过：stdout 输出 `ok <N> records`，退出 0。
- 断链或文件非法：stderr 输出原因，退出 1。

## `adk-agent serve-tool-gateway --tools FILE [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--oidc-config FILE]`

把工具网关作为独立服务运行。

- `FILE` 定义 `tools` 映射，值是 callable 或 `ToolSpec`。
- 只有 `/healthz` 开放。`POST /v1/invoke` 需要 bearer token，非回环地址没 token 拒绝启动。
- 授权以 grants 过线，服务端用 `GrantPolicyEngine` 判定。拒绝和未注册工具返回 403 `{"error":"tool_denied"}`。
- 执行失败返回 502 `{"error":"tool_call_failed"}`，输出不可 JSON 序列化返回 502 `{"error":"tool_output_invalid"}`。
- `GET /metrics` 需要 token，指标见 `metrics.md`。
- 给了 `--audit-file` 时每个 `tool.call` 事件追加一行 JSON。
- 给了 `--audit-url` 时每个事件 `POST` 到 `<url>/v1/events`，期望 202。非 202 或连不上抛 `AuditSinkUnavailable`，当前请求以 502 结束。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。
- 审计 token 从 `--audit-token-env` 指定的环境变量读，默认 `ADK_AUDIT_AUTH_TOKEN`。非回环 URL 没有 token 拒绝启动，退出 1。
- 给了 `--oidc-config` 就改用 OIDC 鉴权，忽略 `--auth-token-env`。和 `--allow-unauthenticated` 互斥。
- OIDC 模式下，请求体的 `invocation.principal` 的 `tenant` 和 `subject` 必须与 token 一致，否则返回 403 `principal_mismatch`。角色、kind、attributes 以 token 为准。

## `adk-agent serve` / `serve-many` 的 MCP HTTP 鉴权

`serve` 和 `serve-many` 的 `streamable-http` 传输支持 `--oidc-config FILE`。

- 给了就改用 OIDC 鉴权，忽略 `--auth-token-env`，允许绑定非回环地址。
- 只对 `streamable-http` 生效。stdio 传输同时给 `--oidc-config` 退出 1。
- 和 `--allow-unauthenticated` 互斥，同时给退出 1。
- 没有 token 或 token 不合法返回 401 `{"error":"unauthorized"}`，签发方不可达返回 503 `{"error":"identity_unavailable"}`。
- `/healthz` 保持开放。
- OIDC 模式下，agent 运行的用户 id 是 token 的 `subject`，会话按 subject 隔离。创建会话时把 `principal` 写进会话 state，键名是 `principal`。
- 静态 token 和未鉴权模式仍使用 ADK 的 `mcp_user`。

## `adk-agent serve` / `serve-many` 的审计、配额与指标

两个命令都接受 `--audit-file PATH | --audit-url URL`、`--audit-token-env VAR`、`--quota-config FILE` 和 `--metrics`。

- 每次 MCP 工具调用在 agent 运行前后写一条 `agent.run` 审计。`target` 是 `<agent>@dev`，`args_hash` 是请求文本的哈希，成功时写 `result_hash`。
- 运行失败写 `status=error`，`error_code` 是异常类名。配额用尽写 `status=denied`、`error_code=quota_exceeded`，并且不运行 agent。
- tenant 取 token 的 principal。没有 principal 的模式（stdio 和静态 token）用 `local`，principal 是 `local` 下的 `mcp_user`。
- `--quota-config` 见 `quota_config.schema.json`，只有列出的租户受限制。`QUOTA_URL` 选择共享后端，规则同控制台。缺 `asyncpg` 时退出 1。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。审计 token 规则同模型网关。
- `--metrics` 在 streamable-http 服务上暴露 `GET /metrics`，并记录运行计数、耗时和配额拒绝。stdio 下只计数，没有端点。
- 指标名和聚合边界见 `metrics.md`。聚合由抓取端做，应用不跨副本共享计数。
- 配置了审计、配额或指标时，`serve` 改用 `serve-many` 的单 agent 形态，以获得同样的运行包装。
- 审计的 `trace_id` 取 `traceparent` 的 trace-id，规则见 `tracing.md`。没有时每次调用新生成。
- `serve` 和 `serve-many` 的 A2A 路径不在这一节范围内。

## `adk-agent serve-a2a --agent FILE [--rpc-path PREFIX] [--host H] [--port P] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--quota-config FILE]`

把一个 agent 暴露成 A2A 端点。

- 需要可选依赖 `a2a-sdk[http-server]>=0.3.4,<2`。没装时退出 1 并给出安装命令。
- 非回环地址必须提供 `--auth-token-env` 指向的 token。loopback 可以 `--allow-unauthenticated`（仅开发）。
- token 保护所有路径，包括 `/.well-known/agent-card.json` 和 JSON-RPC。
- 审计和配额规则同 MCP 一节。tenant 固定 `local`，principal 是 `local` 下的 `a2a_user`，kind 是 `service`。
- 审计的 `args_hash` 取 A2A 消息里文本 part 的拼接，`result_hash` 取最终回复文本。
- 审计的 `trace_id` 取请求头 `traceparent` 的 trace-id，规则见 `tracing.md`。
- 配额拒绝在 A2A 里表现为 task 的 `status.state="failed"`，消息是 `tenant '<name>' exceeded <limit>`，HTTP 状态仍是 200。审计里是 `status=denied`、`error_code=quota_exceeded`。
- 配置了审计或配额且没有传入 runner 时，服务自行构建默认 runner 并包一层。`--audit-file` 和 `--audit-url` 互斥，同时给退出 2。

## `adk-agent console --agents FILE [--policy FILE] [--role ROLE] [--registry DIR] [--oidc-config FILE] [--quota-config FILE] [--approval-dir DIR]`

启动私有控制台。

- `--registry` 指向注册表根目录，默认 `$ADK_REGISTRY_DIR`，否则 `./registry`。只读运营视图从这里读已发布 agent 和评测报告。
- `--oidc-config` 指向一个 `OidcConfig` JSON，见 `oidc_config.schema.json`。给了就改用 OIDC 鉴权，忽略 `--auth-token-env` 和 `--role`。
- `--oidc-config` 和 `--allow-unauthenticated` 互斥，同时给退出 1。OIDC 模式允许绑定非回环地址，因为每个请求都验证 token。
- `--quota-config` 指向一个 `QuotaConfig` JSON，见 `quota_config.schema.json`。只有列出的租户受配额限制，没列出的不限额。
- `QUOTA_URL` 选择共享配额后端，接受 `postgresql://` 或 `postgresql+asyncpg://`。不设置时用进程内计数，只约束单进程。缺少 `asyncpg` 时退出 1 并给出安装提示。
- `--approval-dir` 指向审批收件箱目录，默认 `$ADK_APPROVAL_DIR`。不设置时审批接口返回 404，收件箱禁用。目录在第一次写入时创建。
- `--approval-ttl` 是控制台侧的兜底过期秒数，只作用于没有 `expires_at` 的请求。请求自带 `expires_at` 时以请求为准。不设置时这类请求一直待决。
- 配置文件缺失或非法退出 1。
- `--policy` 指向一个 `AccessPolicy` JSON 文件。给了才启用 RBAC 和 `/api/policy`。
- `--role` 可重复，设置控制台 principal 的角色。默认 `admin`。
- `GET /api/policy` 返回当前策略。`PUT /api/policy` 校验、原子落盘、热替换并写 `policy.update` 审计。
- 聊天按 `agent.run:<agent>` 检查策略。拒绝返回 403 `policy_denied`，并写 `agent.run` `denied` 审计。
- 没给 `--policy` 时控制台不做 RBAC，`/api/policy` 返回 404。

M1 的 `signature` 是 `sha256:<digest>` 完整性标记。它不是密钥签名，M4 会替换。
