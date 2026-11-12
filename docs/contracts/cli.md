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

## `adk-agent serve-model-gateway [--provider NAME]... [--vllm-url URL] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR]`

把模型网关作为独立服务运行。

- 默认 provider 是 `litellm`。`--provider vllm` 需要 `--vllm-url` 或 `$VLLM_BASE_URL`。
- 只有 `/healthz` 开放。`POST /v1/complete` 需要 bearer token，非回环地址没 token 拒绝启动。
- 策略拒绝返回 403 `{"error":"model_denied"}`，provider 失败返回 502 `{"error":"model_call_failed"}`。
- 给了 `--audit-file` 时每个 `model.call` 事件追加一行 JSON。
- 给了 `--audit-url` 时每个事件 `POST` 到 `<url>/v1/events`，期望 202。非 202 或连不上抛 `AuditSinkUnavailable`，当前请求以 502 结束。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。
- 审计 token 从 `--audit-token-env` 指定的环境变量读，默认 `ADK_AUDIT_AUTH_TOKEN`。非回环 URL 没有 token 拒绝启动，退出 1。

## `adk-agent serve-audit --out FILE`

把审计管线作为独立服务运行。

- 只有 `/healthz` 开放。`POST /v1/events` 需要 bearer token，非回环地址没 token 拒绝启动。
- 成功返回 202 `{"hash":"..."}`。写入失败返回 502 `{"error":"audit_write_failed"}`。
- `FILE` 每行一条 `AuditRecord`，同租户串成哈希链，每租户首条 `prev_hash` 为空串。

## `adk-agent verify-audit FILE`

逐条重算审计链。

- 通过：stdout 输出 `ok <N> records`，退出 0。
- 断链或文件非法：stderr 输出原因，退出 1。

## `adk-agent serve-tool-gateway --tools FILE [--audit-file PATH | --audit-url URL] [--audit-token-env VAR]`

把工具网关作为独立服务运行。

- `FILE` 定义 `tools` 映射，值是 callable 或 `ToolSpec`。
- 只有 `/healthz` 开放。`POST /v1/invoke` 需要 bearer token，非回环地址没 token 拒绝启动。
- 授权以 grants 过线，服务端用 `GrantPolicyEngine` 判定。拒绝和未注册工具返回 403 `{"error":"tool_denied"}`。
- 执行失败返回 502 `{"error":"tool_call_failed"}`，输出不可 JSON 序列化返回 502 `{"error":"tool_output_invalid"}`。
- 给了 `--audit-file` 时每个 `tool.call` 事件追加一行 JSON。
- 给了 `--audit-url` 时每个事件 `POST` 到 `<url>/v1/events`，期望 202。非 202 或连不上抛 `AuditSinkUnavailable`，当前请求以 502 结束。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。
- 审计 token 从 `--audit-token-env` 指定的环境变量读，默认 `ADK_AUDIT_AUTH_TOKEN`。非回环 URL 没有 token 拒绝启动，退出 1。

## `adk-agent serve-a2a --agent FILE [--rpc-path PREFIX] [--host H] [--port P]`

把一个 agent 暴露成 A2A 端点。

- 需要可选依赖 `a2a-sdk[http-server]>=0.3.4,<2`。没装时退出 1 并给出安装命令。
- 非回环地址必须提供 `--auth-token-env` 指向的 token。loopback 可以 `--allow-unauthenticated`（仅开发）。
- token 保护所有路径，包括 `/.well-known/agent-card.json` 和 JSON-RPC。

## `adk-agent console --agents FILE [--policy FILE] [--role ROLE]`

启动私有控制台。

- `--policy` 指向一个 `AccessPolicy` JSON 文件。给了才启用 RBAC 和 `/api/policy`。
- `--role` 可重复，设置控制台 principal 的角色。默认 `admin`。
- `GET /api/policy` 返回当前策略。`PUT /api/policy` 校验、原子落盘、热替换并写 `policy.update` 审计。
- 聊天按 `agent.run:<agent>` 检查策略。拒绝返回 403 `policy_denied`，并写 `agent.run` `denied` 审计。
- 没给 `--policy` 时控制台不做 RBAC，`/api/policy` 返回 404。

M1 的 `signature` 是 `sha256:<digest>` 完整性标记。它不是密钥签名，M4 会替换。
