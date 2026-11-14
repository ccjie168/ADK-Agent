# CLI 契约

## 审计后端选择

接受 `--audit-file`/`--audit-url` 的命令同时接受 `--audit-db URL`，三者互斥。

- `--audit-file PATH` 追加 JSONL；`--audit-url URL` 发给审计服务；`--audit-db URL` 直接写 `adk_audit_records`。
- 三者都未显式给出时读 `AUDIT_DATABASE_URL`；给了 file 或 url 时忽略该环境变量。显式参数与环境变量冲突也退出 2。
- DB 模式使用 `PostgresAuditSink`/`PostgresAuditQuery`，链语义与文件模式相同，每个租户一条链。
- 签名沿用 `ADK_AUDIT_KEYRING`/`ADK_AUDIT_SIGNING_KEY`。使用签名时，所有写者必须共享同一个密钥环，否则后续 `verify-audit --audit-db` 会按断链或签名失败拒绝。
- 错误消息不回显 DSN 或密钥。

## `adk-agent validate <path>`

解析并校验 `AgentManifest` JSON。

- 成功：stdout 输出 `tenant/id@version sha256:<digest>`，退出 0。
- 失败：stderr 输出 `invalid manifest: <原因>`，退出 1。
- 未知字段、非法 `id` / `version` / `tenant`、缺失必填字段都算失败。

## `adk-agent publish <path> [--registry DIR] [--eval-report FILE] [--artifact DIR|ZIP --key FILE --key-id ID] [--artifact-dir DIR | $ARTIFACT_URL]`

校验 manifest，跑评测门禁，计算 digest，写入注册表。

- manifest 声明 `eval_suite` 时必须给 `--eval-report`，且报告的 `suite_id`、`version` 一致，`score` 不低于 `pass_threshold`。否则退出 1，不写注册表。
- 成功：stdout 输出 `published tenant/id@version sha256:<digest>`，退出 0。
- 重复发布相同内容：幂等成功，返回已存记录。
- 同版本不同内容：stderr 输出 `publish failed: <原因>`，退出 1。
- 通过门禁的报告写到 `<registry>/<tenant>/<id>/<version>.eval.json`。相同报告重复发布幂等，不同报告退出 1。
- 报告写失败退出 1，版本可能已写入；重新发布同一 manifest 会把报告补上。
- `--artifact DIR|ZIP` 附加工件。`DIR` 必须含 `manifest.json` 和入口 `agent.py`，可选 `requirements.txt`、`README.md`；打包成字节级确定的 zip（条目排序、时间戳 1980-01-01、权限 0644、不压缩）。`ZIP` 输入必须是同一 manifest 的工件，内容不符退出 1。工件上限 8 MiB。
- 带工件发布必须给 `--key FILE`（PEM Ed25519 私钥）和 `--key-id ID`；签名是私钥对 `sha256:<hex>` 摘要的 Ed25519 签名，128 hex。缺任一参数退出 1。`--key` 配 `--key-id` 但不给 `--artifact` 也退出 1。
- 工件字节写到 `--artifact-dir DIR`（内容寻址目录）或 `ARTIFACT_URL`（`postgresql://` 共享库），两者只能给一个；带工件发布且都没给时退出 1。
- 成功输出第一行不变，有工件时第二行输出 `artifact sha256:<hex>`。
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

## `adk-agent serve-model-gateway [--provider NAME]... [--vllm-url URL] [--breaker-failures N] [--breaker-reset SECONDS] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--oidc-config FILE] [--rate-limit N --rate-limit-window SECONDS]`

把模型网关作为独立服务运行。

- 每个 provider 有独立的熔断器。连续失败 N 次后打开，`--breaker-failures` 默认 5，`--breaker-reset` 默认 30 秒。
- 打开期间不调用 provider，直接返回 503 `{"error":"model_unavailable"}`。重置时间过后放行一次探测，成功关闭，失败重新打开。
- 两个参数都必须大于 0，否则退出 1。短路计数见 `metrics.md`。

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

## `adk-agent serve-audit (--out FILE | --audit-db URL) [--audit-max-records N] [--oidc-config FILE] [--rate-limit N --rate-limit-window SECONDS]`

把审计管线作为独立服务运行。

- `--out` 与 `--audit-db` 二选一；两者都不给时读 `AUDIT_DATABASE_URL`，仍没有则退出 2。
- 只有 `/healthz` 开放。`POST /v1/events` 需要 bearer token，非回环地址没 token 拒绝启动。
- 成功返回 202 `{"hash":"..."}`。写入失败返回 502 `{"error":"audit_write_failed"}`。DB 模式返回的哈希与写入 `adk_audit_records` 的 `hash` 相同。
- `FILE` 每行一条 `AuditRecord`，同租户串成哈希链，每租户首条 `prev_hash` 为空串。
- DB 模式写入 `adk_audit_records`，每租户按 `sequence` 串链；`GET /v1/events` 从同一后端读取。
- `--audit-max-records` 只适用于文件模式，与 `--audit-db` 同时给出退出 2。大于 0 时按段轮转。当前段写满 N 条后改名为 `FILE.000001`、`FILE.000002`，新记录继续写 `FILE`。哈希链跨段连续。
- 设置了 `ADK_AUDIT_KEYRING` 时使用密钥环：值是 JSON `{"active": "<kid>", "keys": {"<kid>": "<key>", ...}, "legacy": "<kid>"}`。新记录用 `active` 对应的密钥对 `hash` 做 HMAC-SHA256，并把 `active` 写入 `kid`。`legacy` 可选，指定没有 `kid` 的旧记录用哪把密钥验签。`active` 必须在 `keys` 里，`legacy` 给了也必须在 `keys` 里，密钥不能为空，`kid` 必须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`。
- 没有密钥环但设置了 `ADK_AUDIT_SIGNING_KEY` 时，沿用单密钥模式：签名写入 `signature`，`kid` 为 `null`。
- 两个变量同时设置时退出 1。密钥只从环境变量读，不出现在命令行和仓库里。
- 给了 `--oidc-config` 就改用 OIDC 鉴权，忽略 `--auth-token-env`。和 `--allow-unauthenticated` 互斥。
- OIDC 模式下，事件的 `tenant` 和 `principal.subject` 必须与 token 一致，否则返回 403 `principal_mismatch`。角色、kind、attributes 以 token 为准。

## 连接器工具（`serve-tool-gateway`）

`serve-tool-gateway` 可以把已注册的连接器暴露为工具。

- `--connectors-dir DIR` 或 `$CONNECTOR_URL` 选择连接器存储，二选一；都不给时只加载 `--tools`。
- `--connector-tenant TENANT` 决定加载哪些连接器（全局 + 该租户），默认 `local`。
- 每个启用的连接器生成一个工具，工具 id 是 `connector_id`，参数是 `path`、`method`、`query`、`json_body`。
- 出站只允许 `methods` 与 `path_prefixes` 覆盖的请求，host/scheme 固定，禁止重定向；超时与响应大小按连接器配置。
- 凭据用 `secret://a/b` 引用，映射到环境变量 `ADK_SECRET_A_B`；缺失时调用拒绝，错误码 `secret_unavailable`。
- 连接器工具的 `tool.call` 审计带 `egress=third_party`；越界错误码是 `egress_denied`、`method_denied`、`path_denied`、`response_too_large` 或 `connector_unavailable`。

## `GET /v1/events`（审计服务的只读查询）

审计服务在 `POST /v1/events` 之外提供只读查询，供控制台和其他治理视图使用。

查询参数，全部可选：

- `tenant`：租户。OIDC 模式下缺省取 token 的租户；非 `admin` 角色查询其他租户返回 403 `tenant_forbidden`。静态 token 和回环免鉴权模式不做租户限制。
- `trace_id`、`run_id`、`action`：精确匹配。
- `status`：`ok`、`error` 或 `denied`，其他值返回 400 `invalid_status`。
- `since`、`until`：ISO-8601 时间，必须带时区，闭区间，非法值返回 400 `invalid_time`。
- `limit`：1 到 1000，默认 100，越界返回 400 `invalid_limit`。
- `order`：`desc`（默认，最新在前）或 `asc`，其他值返回 400 `invalid_order`。

成功返回 200 `{"events": [AuditEvent], "count": <本次返回条数>}`。事件按时间排序，同一时间按写入顺序。读取正在写入的当前段时，末尾未写完的半行被忽略；其他解析失败返回 502 `audit_read_failed`。

鉴权规则与写入相同，见上一节。

## `adk-agent tool-grants list|request|decide [--tool-grants-dir DIR | $GRANT_URL]`

管理工具临时授权请求。存储配置与 `console` 相同，二选一。

- `list --tenant T [--status S]` 打印 JSON 数组。
- `request --tenant T --id ID --version V --digest D --tool TOOL --reason TEXT [--expires-hours N]` 创建 pending 请求并打印记录。不校验版本是否存在；服务端与控制台的 `POST /api/tool-grants` 会校验。
- `decide REQUEST_ID (--approve | --deny) [--reason TEXT]` 审批，打印更新后的记录。
- 非法状态、过期小时越界、存储错误都退出 1。

## `adk-agent lifecycle set --tenant T --id ID --version V --status S [--reason TEXT] [--registry DIR | --registry-url URL [--registry-token-env VAR]]`

修改已发布版本的生命周期状态，语义见 ADR-0010 与 `registry_service.md`。

- `--status` 取 `published`、`deprecated`、`retired`，其他值退出 1。
- `--registry-url` 走控制面 `PUT .../lifecycle`；否则用 `--registry` 目录下的文件实现。
- 版本不存在、非法转换或服务不可达退出 1。成功打印 `TENANT/ID@VERSION status=STATUS`。
- `changed_by` 在文件模式下是 `cli`；HTTP 模式由服务端按调用方记录。

`console`、`serve`、`serve-many` 从注册表加载时也会检查状态：退役版本启动失败退出 1。控制台按需加载对退役版本返回 409。

## `adk-agent backup --out FILE [--registry DIR] [--approvals DIR] [--audit FILE]`

把文件型状态打成一个 gzip tar 包。

- 至少给一个来源，否则退出 1。来源不存在也退出 1。
- 归档内用 `registry/`、`approvals/`、`audit/` 前缀。`--audit` 会连同 `<FILE>.000001` 这类轮转段一起打包。
- 包里有 `manifest.json`，内容至少包含 `version`（当前是 1）、`created_at` 和每个来源的文件数与字节数。
- 成功后 stdout 输出 `wrote <path> sha256:<hex>`，退出 0。文件权限设为 0600（POSIX）。
- 不包含 Postgres 里的会话和配额数据。这些用 `pg_dump` 单独备份。

## `adk-agent restore --archive FILE --dest DIR [--force]`

把备份解到 `DIR`。

- `DIR` 必须不存在或为空，否则退出 1。`--force` 时先完整解到临时目录，成功后替换 `DIR`。
- 解包使用安全过滤器，拒绝绝对路径和 `..`，失败退出 1。
- 必须有版本为 1 的 `manifest.json`，缺失或版本不符退出 1。
- 成功后 stdout 输出 `restored <N> files to <path>`，退出 0。
- 解包失败不留下半成品目录。

## `adk-agent connectors list|register|disable`

管理外部 API 连接器（ADR-0013）。

- `--connectors-dir DIR` 用文件存储；`--registry-url URL` 用控制面服务。二选一，必须提供一个。
- `connectors list --tenant TENANT` 输出 JSON 数组，含全局与租户连接器。
- `connectors register` 接受 `--id`、`--kind`（http/openapi/mcp）、`--base-url`、`--auth-ref`、`--methods`（逗号分隔）、`--path-prefixes`（逗号分隔）、`--data-classes`（逗号分隔）、`--timeout-seconds`、`--max-response-bytes`、可选 `--tenant`。输出已存记录的 JSON；同 id 不同定义退出 1。
- `connectors disable --id ID` 输出停用后的 JSON。未知 id 退出 1。
- `connectors check --id ID` 输出 `ConnectorHealth` JSON，从 CLI 进程探测第一个路径前缀，不带凭据、不跟随重定向、超时不超过 5 秒。未知 id 退出 1；探测失败也输出结果并退出 0，因为结果本身就是检查结论。
- 成功写 `connector.register` 或 `connector.disable` 审计；控制面模式下写端要求 admin。

## `adk-agent peers list|register|disable|grant|revoke`

管理 A2A peer 与其动作授权（ADR-0014）。

- `--peer-dir DIR` 或 `--peer-db URL` 指定存储，二选一，必须提供一个。控制台 `console` 也接受同样两个参数。
- `peers list [--tenant T]` 输出 `[{"peer": PeerIdentity, "grants": [PeerGrant]}]`，按 `peer_id` 排序。
- `peers register --id ID --tenant T [--subject S] [--kind service|human|agent] [--roles A,B]` 输出 peer。已存在但改租户退出 1。
- `peers disable --id ID` 输出停用后的 peer，幂等。
- `peers grant --id ID --agent AGENT --actions read,invoke` 输出授权。未知动作或空列表退出 1。
- `peers revoke --id ID --agent AGENT` 输出 `{"revoked": bool}`，授权不存在也退出 0。
- 控制台的写操作写 `peer.register`、`peer.disable`、`peer.grant` 或 `peer.revoke` 审计。CLI 直接写存储，不产生审计，与现有 `connectors`、`lifecycle` 命令一致。

## `adk-agent remote-agents list|register|refresh|disable`

管理远端 A2A agent 的目录记录（ADR-0015）。

- 存储参数复用 `--peer-dir DIR` 或 `--peer-db URL`，二选一；记录写在 `<DIR>/remote-agents/<remote_id>.json` 或 `adk_remote_agents` 表。
- `remote-agents list [--tenant T]` 输出 JSON 数组，按 `remote_id` 排序。
- `remote-agents register --id ID --tenant T --peer P --card-url URL [--credential-ref REF] [--label L]` 拉取 card、校验名称并输出记录；已存在记录改租户退出 1；其他失败按契约错误退出 1。
- `remote-agents refresh --id ID` 输出刷新后的记录；`changed` 与 `unreachable` 也退出 0，结论写在记录里。
- `remote-agents disable --id ID` 输出停用后的记录，幂等；未知 id 退出 1。
- 凭据经 `ADK_SECRET_*` 环境变量解析，命令不打印凭据。

## `adk-agent approvals prune (--dir DIR | --db URL) --older-than SECONDS [--delete]`

归档或删除已经终结、且超过保留期的审批记录。

- `--dir` 默认 `$ADK_APPROVAL_DIR`；`--db` 默认 `$APPROVAL_DATABASE_URL`。
- 显式 `--db` 优先于 `ADK_APPROVAL_DIR`，显式 `--dir` 优先于 `APPROVAL_DATABASE_URL`。两个显式 flag 同时给出退出 1；只有环境变量时 `APPROVAL_DATABASE_URL` 优先；两个后端都没有时退出 1。
- `--older-than` 必须是大于 0 的秒数，否则退出 1。
- 终结时间取决定的 `decided_at`；没有决定但已过期的请求取 `expires_at`。没有决定且未过期的请求永远保留。数据库模式用数据库的 `now()` 计算保留期。
- 默认把文件移到 `<dir>/archive/`，或把数据库行搬到 `adk_approvals_archive`。归档里已有同名记录时跳过该条，源记录保留。
- `--delete` 改为删除，不归档。
- 成功输出 `archived N requests` 或 `deleted N requests`，退出 0。
- 数据库不可达或 schema 初始化失败时退出 1，只打印固定错误种类。
- 这个命令不写审计事件。

## `adk-agent verify-audit FILE | --audit-db URL`

逐条重算审计链，包括 `FILE.000001` 这类轮转段，按序号顺序处理。

- `FILE` 与 `--audit-db` 二选一，同时给或都不给退出 2。
- `--audit-db` 接受 `postgresql://` 或 `postgresql+asyncpg://`，按租户读取 `adk_audit_records` 并按 `sequence` 遍历，链算法与文件模式相同。
- 数据库模式下的输出与退出码与文件模式一致；断链时报告租户与记录序号。

- 通过：stdout 输出 `ok <N> records`，退出 0。
- 断链或文件非法：stderr 输出原因，退出 1。
- 设置了 `ADK_AUDIT_KEYRING` 时按记录的 `kid` 选密钥验签：未知 `kid` 退出 1；没有 `kid` 的记录用 `legacy` 指定的密钥，没给 `legacy` 时退出 1。`ADK_AUDIT_SIGNING_KEY` 单密钥模式要求每条记录都没有 `kid` 且签名匹配。两个变量同时设置时退出 1。都设置时以外的缺失签名也退出 1。没设置任何密钥时只验哈希链。
- 轮换步骤：把新密钥加进 `keys`，把 `active` 指向它，保留旧密钥；如果旧历史没有 `kid`，把 `legacy` 指向旧密钥。全部旧记录验完之前不要删掉旧密钥。

## `adk-agent serve-tool-gateway [--tools FILE] [--connectors-dir DIR | $CONNECTOR_URL] [--connector-tenant TENANT] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--oidc-config FILE] [--rate-limit N --rate-limit-window SECONDS]`

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

## `adk-agent serve-registry --database-url URL [--artifact-dir DIR | $ARTIFACT_URL] [--artifact-keys FILE | $ADK_ARTIFACT_KEYS] [--oidc-config FILE] [--rate-limit N --rate-limit-window SECONDS]`

启动注册表控制面服务，接口见 `registry_service.md`。

- `--database-url` 指向 Postgres，接受 `postgresql://` 或 `postgresql+asyncpg://`；默认取 `$REGISTRY_DATABASE_URL`。缺失或非 Postgres 退出 1。
- 工件字节存储用 `--artifact-dir DIR` 或 `$ARTIFACT_URL`，二选一；都不给时带工件的发布和工件上传返回 503 `artifact_store_unavailable`，不带工件的发布与读取照常。两者同时给退出 1。
- `--artifact-keys` 或 `$ADK_ARTIFACT_KEYS` 提供可信公钥，用于发布与上传时验签。
- 鉴权、`/healthz`、限流与其他服务一致。

## 客户端 `--registry-url URL [--registry-token-env VAR]`

`console`、`serve`、`serve-many` 和 `publish` 接受这两个参数。给了 `--registry-url` 时注册表元数据走 HTTP，忽略 `--registry DIR`；`--registry-token-env` 默认 `ADK_REGISTRY_AUTH_TOKEN`，token 只从环境变量读。

- `console`、`serve`、`serve-many` 的运行工件仍从 `--artifact-dir` 或 `$ARTIFACT_URL` 读取，可信公钥仍为必需。
- `publish --registry-url` 先 `POST /v1/agents`；带 `--artifact` 时再用 `PUT /v1/artifacts/{digest}` 上传字节。此模式下 `--artifact-dir` 与 `$ARTIFACT_URL` 不参与，同时给退出 1。
- `publish --registry-url` 带 `--eval-report` 时在发布记录后用 `PUT /v1/agents/{tenant}/{id}/{version}/eval` 上传报告，顺序是记录、报告、工件字节。

## 从注册表启动（`console` / `serve` / `serve-many`）

`console`、`serve` 和 `serve-many` 可以用 `--agent-ref TENANT/ID@VERSION` 代替本地 agent 文件。可重复。

- `--agent-ref` 与 `--agents`（或 `serve` 的 `--agent`/`--config`）互斥，同时给退出 1。二者都不给也退出 1。
- 加载前要求两个配置：工件字节来源 `--artifact-dir DIR` 或 `ARTIFACT_URL`（互斥，必须给一个），以及可信公钥 `--artifact-keys FILE` 或 `ADK_ARTIFACT_KEYS`（JSON 映射 `key_id -> 64 hex 公钥`）。缺任一项退出 1。
- 解析顺序：按租户列出注册表，找 `id@version`，用记录摘要调 `load_agent`；工件必须存在，签名必须被信任，否则退出 1。
- agent 的名字取 manifest 的 `id`；同一批里重名退出 1。
- `serve` 只接受一个 `--agent-ref`。

## `adk-agent serve` / `serve-many` 的 MCP HTTP 鉴权

`serve` 和 `serve-many` 的 `streamable-http` 传输支持 `--oidc-config FILE`。

- 给了就改用 OIDC 鉴权，忽略 `--auth-token-env`，允许绑定非回环地址。
- 只对 `streamable-http` 生效。stdio 传输同时给 `--oidc-config` 退出 1。
- 和 `--allow-unauthenticated` 互斥，同时给退出 1。
- 没有 token 或 token 不合法返回 401 `{"error":"unauthorized"}`，签发方不可达返回 503 `{"error":"identity_unavailable"}`。
- `/healthz` 保持开放。
- OIDC 模式下，agent 运行的用户 id 是 token 的 `subject`，会话按 subject 隔离。创建会话时把 `principal` 写进会话 state，键名是 `principal`。
- 静态 token 和未鉴权模式仍使用 ADK 的 `mcp_user`。

## `serve` / `serve-many` / `serve-a2a` 的工具授权

三个运行命令在启动时给 agent 树安装工具守卫。

- 允许清单：按 `--agent-ref` 加载时取已发布 manifest 的 `tool_grants`；否则取 agent 树声明的工具（`BaseTool`、toolset 与函数工具）。
- 清单外的工具调用返回 `{"error": "tool_denied", ...}`，工具不执行。
- 配置审计时写 `tool.call` 事件，`status=ok` 或 `denied`；没有审计时仍然拦截。
- 控制台行为不变，仍然按声明工具安装守卫。

## `console` / `serve` / `serve-many` 的临时工具授权

三个命令接受 `--tool-grants-dir DIR` 或 `GRANT_URL`（`postgresql://` 或 `postgresql+asyncpg://`），二选一，都不给时只用 manifest 与声明工具。

- 配置后，工具调用在 manifest 授权之外再查一次“已批准且未过期”的临时授权，锚点是 `(tenant, agent_id, version, digest, tool_id)`。
- 每次调用查询，不加缓存；存储不可达时拒绝，审计错误码为 `grant_store_unavailable`。
- 两者同时给退出 1；`GRANT_URL` 需要 `asyncpg`，缺失时退出 1。

## `adk-agent serve` / `serve-many` 的审计、配额与指标

两个命令都接受 `--audit-file PATH | --audit-url URL`、`--audit-token-env VAR`、`--quota-config FILE`、`--metrics`、`--rate-limit N --rate-limit-window SECONDS`、`--session-tenant-scope` 和 `--session-rls`。

- 每次 MCP 工具调用在 agent 运行前后写一条 `agent.run` 审计。`target` 是 `<agent>@dev`，`args_hash` 是请求文本的哈希，成功时写 `result_hash`。
- 运行失败写 `status=error`，`error_code` 是异常类名。配额用尽写 `status=denied`、`error_code=quota_exceeded`，并且不运行 agent。
- tenant 取 token 的 principal。没有 principal 的模式（stdio 和静态 token）用 `local`，principal 是 `local` 下的 `mcp_user`。
- `--quota-config` 见 `quota_config.schema.json`，只有列出的租户受限制。`QUOTA_URL` 选择共享后端，规则同控制台。缺 `asyncpg` 时退出 1。
- `--audit-file` 和 `--audit-url` 互斥，同时给退出 2。审计 token 规则同模型网关。
- `--metrics` 在 streamable-http 服务上暴露 `GET /metrics`，并记录运行计数、耗时和配额拒绝。stdio 下只计数，没有端点。
- 指标名和聚合边界见 `metrics.md`。聚合由抓取端做，应用不跨副本共享计数。
- 配置了审计、配额或指标时，`serve` 改用 `serve-many` 的单 agent 形态，以获得同样的运行包装。
- `--rate-limit N --rate-limit-window SECONDS` 只对 `streamable-http` 生效，语义见「入口限流」。
  配 `stdio` 同时给 `--rate-limit` 退出 1。
- `--session-tenant-scope` 只对 OIDC 模式的 `streamable-http` 生效。打开后 OIDC 会话键从 `<subject>` 变成 `<tenant>:<subject>`，同一 subject 跨租户的会话和会话缓存互不可见。默认关闭；开启后旧会话按旧键存在，不会出现。
- `--session-rls` 需要 `--session-tenant-scope` 和 Postgres 的 `SESSION_URL`，语义见「会话存储的租户 RLS」。
- 审计的 `trace_id` 取 `traceparent` 的 trace-id，规则见 `tracing.md`。没有时每次调用新生成。
- `serve` 和 `serve-many` 的 A2A 路径不在这一节范围内。

## `adk-agent serve-a2a --agent FILE [--rpc-path PREFIX] [--host H] [--port P] [--audit-file PATH | --audit-url URL] [--audit-token-env VAR] [--quota-config FILE] [--rate-limit N --rate-limit-window SECONDS]`

把一个 agent 暴露成 A2A 端点。

- 需要可选依赖 `a2a-sdk[http-server]>=0.3.4,<2`。没装时退出 1 并给出安装命令。
- 非回环地址必须提供 `--auth-token-env` 指向的 token。loopback 可以 `--allow-unauthenticated`（仅开发）。
- token 保护所有路径，包括 `/.well-known/agent-card.json` 和 JSON-RPC。
- 审计和配额规则同 MCP 一节。tenant 固定 `local`，principal 是 `local` 下的 `a2a_user`，kind 是 `service`。
- 审计的 `args_hash` 取 A2A 消息里文本 part 的拼接，`result_hash` 取最终回复文本。
- 审计的 `trace_id` 取请求头 `traceparent` 的 trace-id，规则见 `tracing.md`。
- 配额拒绝在 A2A 里表现为 task 的 `status.state="failed"`，消息是 `tenant '<name>' exceeded <limit>`，HTTP 状态仍是 200。审计里是 `status=denied`、`error_code=quota_exceeded`。
- 配置了审计或配额且没有传入 runner 时，服务自行构建默认 runner 并包一层。`--audit-file` 和 `--audit-url` 互斥，同时给退出 2。
- `--rate-limit N --rate-limit-window SECONDS` 按客户端地址计数，对所有路径生效。A2A 没有 `/healthz` 和 `/metrics`，没有豁免路径。

peer 模式（ADR-0014，见 `a2a.md`）：

- `--peer-dir DIR` 或 `--peer-db URL` 提供 peer 与授权存储，二选一。
- 身份用 `--oidc-config FILE` 或 `--peer-token-file FILE`，二选一，且都必须配合 peer 存储。
- 必须同时提供 `--manifest FILE`，manifest 的 `exposure` 必须是 `a2a`。
- peer 模式与 `--auth-token-env`、`--allow-unauthenticated` 互斥，同时给出退出 2。
- peer 模式下 principal、审计身份、动作映射与拒绝规则见 `a2a.md`；legacy 模式保持本节原有行为。

## `adk-agent console [--agents FILE | --agent-ref TENANT/ID@VERSION] [--policy FILE] [--role ROLE] [--registry DIR] [--tool-catalog FILE] [--oidc-config FILE] [--quota-config FILE] [--approval-dir DIR | --approval-db URL] [--sse-queue-size N] [--rate-limit N --rate-limit-window SECONDS] [--session-tenant-scope] [--session-rls]`

启动私有控制台。

- `--registry` 指向注册表根目录，默认 `$ADK_REGISTRY_DIR`，否则 `./registry`。只读运营视图从这里读已发布 agent 和评测报告。
- `--tool-catalog` 指向只读工具目录 JSON，结构是 `{"version": 1, "tools": [ToolEntry...]}`。`ToolEntry` 字段：`tool_id`、`description`、`source`（`function`/`openapi`/`mcp`/`connector`）、`data_classes`、`requires_approval`、可选 `tenant`。重复 `tool_id` 或非法字段退出 1。不给时工具面板返回 404。
- `--oidc-config` 指向一个 `OidcConfig` JSON，见 `oidc_config.schema.json`。给了就改用 OIDC 鉴权，忽略 `--auth-token-env` 和 `--role`。
- `--oidc-config` 和 `--allow-unauthenticated` 互斥，同时给退出 1。OIDC 模式允许绑定非回环地址，因为每个请求都验证 token。
- `--quota-config` 指向一个 `QuotaConfig` JSON，见 `quota_config.schema.json`。只有列出的租户受配额限制，没列出的不限额。
- `QUOTA_URL` 选择共享配额后端，接受 `postgresql://` 或 `postgresql+asyncpg://`。不设置时用进程内计数，只约束单进程。缺少 `asyncpg` 时退出 1 并给出安装提示。
- `--approval-dir` 指向审批收件箱目录，默认 `$ADK_APPROVAL_DIR`。`--approval-db` 指向 Postgres 审批库，默认 `$APPROVAL_DATABASE_URL`。两者二选一：显式 flag 优先于环境变量，两个显式 flag 同时给出退出 1。都不设置时审批接口返回 404，收件箱禁用。目录在第一次写入时创建。
- `--approval-ttl` 是控制台侧的兜底过期秒数，只作用于没有 `expires_at` 的请求。请求自带 `expires_at` 时以请求为准。不设置时这类请求一直待决。数据库模式把派生出的截止时间写入行。
- `--sse-queue-size` 是每条 SSE 流最多缓冲的 `progress` 事件数，默认 512。必须大于 0，否则退出 1。慢客户端超过缓冲时丢弃最早的 `progress`，丢弃数在终结事件里报，见 `console.md`。
- `--audit-file PATH` 把审计事件追加到 JSONL；`--audit-url URL` 改建到审计服务，读面板（审计、运行、trace）也从该服务查询。两者互斥，同时给退出 2。审计 token 从 `--audit-token-env` 指定（默认 `ADK_AUDIT_AUTH_TOKEN`），非回环地址没有 token 时拒绝启动。都不给时审计只留在进程内，多副本之间不共享。
- `--session-tenant-scope` 打开后，控制台的会话键从 `<subject>` 变成 `<tenant>:<subject>`，同一 subject 在不同租户下的会话互不可见。默认关闭。开启后已有会话按旧键存在，不会出现在列表里，等价于让所有用户重新开始会话。
- `--session-rls` 需要 `--session-tenant-scope` 和 Postgres 的 `SESSION_URL`，语义见「会话存储的租户 RLS」。
- `--rate-limit` 和 `--rate-limit-window` 启用入口限流，语义见下面的「入口限流」一节。不给 `--rate-limit` 时不限流。
- 配置文件缺失或非法退出 1。
- `--policy` 指向一个 `AccessPolicy` JSON 文件。给了才启用 RBAC 和 `/api/policy`。
- `--role` 可重复，设置控制台 principal 的角色。默认 `admin`。
- `GET /api/policy` 返回当前策略。`PUT /api/policy` 校验、原子落盘、热替换并写 `policy.update` 审计。
- 聊天按 `agent.run:<agent>` 检查策略。拒绝返回 403 `policy_denied`，并写 `agent.run` `denied` 审计。
- 没给 `--policy` 时控制台不做 RBAC，`/api/policy` 返回 404。

M1 的 `signature` 是 `sha256:<digest>` 完整性标记。它不是密钥签名，M4 会替换。

## 会话存储的租户 RLS（ADR-0019）

`console`、`serve`、`serve-many` 接受 `--session-rls`。它只在 `SESSION_URL` 是 `postgresql://` 或 `postgresql+asyncpg://` 且 `--session-tenant-scope` 打开时可用，其他组合退出 1。

- 打开后，`sessions`、`events`、`user_states` 三张表启用并强制 RLS，策略是 `split_part(user_id, ':', 1) = current_setting('app.tenant_id', true)`，`USING` 与 `WITH CHECK` 都要。
- 租户取自已认证 principal。运行外的会话调用由控制台与 MCP 的调用点设置请求上下文；运行路径回退到 `current_invocation().principal.tenant`。`user_id` 只用于行匹配，不决定租户。
- 每个事务在 `after_begin` 时执行 `set_config('app.tenant_id', <tenant>, true)`。没有租户时读到 0 行。
- 启动时检查三张表的 `relrowsecurity`、`relforcerowsecurity` 与策略存在；缺失时退出 1，提示先运行 `adk-agent sessions enable-rls`。
- `app_states` 不在 RLS 范围。租户敏感的应用级状态不能放在那里。
- 打开后没有冒号前缀的 `user_id` 行不可见，不自动迁移。

## `adk-agent sessions enable-rls --database-url URL`

为 ADK 会话表安装 RLS 策略。

- URL 必须是 Postgres；不给时读 `SESSION_URL`。两者都没有退出 1，SQLite 与内存存储退出 1。
- 执行角色必须是 `sessions`、`events`、`user_states` 的属主，不能是 superuser，不能有 `BYPASSRLS`；否则退出 1。
- 表不存在时退出 1，提示先创建一次会话。
- 幂等：重复运行先 `DROP POLICY IF EXISTS` 再重建。
- 成功输出 `session rls enabled`，退出 0。

## 入口限流

`console`、`serve-model-gateway`、`serve-tool-gateway` 和 `serve-audit` 接受 `--rate-limit N` 和 `--rate-limit-window SECONDS`（默认 60）。

- 不给 `--rate-limit` 时不限流。`--rate-limit` 必须是大于 0 的整数，`--rate-limit-window` 必须是大于 0 的秒数，否则退出 1。只给 `--rate-limit-window` 也退出 1。
- 计数键是 principal 的 `tenant:subject`；没有 principal 的模式（静态 token、未鉴权）用客户端地址。
- 固定窗口。超过上限返回 429 `{"error":"rate_limited"}`，并带 `Retry-After` 秒数。
- `/healthz` 不限流。暴露 `/metrics` 的服务也豁免 `/metrics`，避免抓取被限流。鉴权在限流之前，没有 token 的请求仍返回 401。
- 计数默认在进程内。设置 `RATE_LIMIT_URL`（`redis://` 或 `rediss://`）后改用 Redis 共享计数，副本间共享一个窗口；未设置时行为不变。
- Redis 不可达时退回进程内计数并记 `adk_rate_limit_backend_errors_total{surface}`，不会因为缓存故障拒绝全部请求。缺少 `redis` 客户端时配置了 URL 的启动会失败并提示安装 `adk-agent[redis]`。
- MCP 的 streamable-http 也支持这两个参数，计数键优先用 OIDC principal，否则用客户端地址；`/healthz` 和 `/metrics` 豁免。A2A 端点只支持静态 token，按客户端地址计数，无豁免路径。
- 拒绝计数见 `metrics.md`。
