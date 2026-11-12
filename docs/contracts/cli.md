# CLI 契约

## `adk-agent validate <path>`

解析并校验 `AgentManifest` JSON。

- 成功：stdout 输出 `tenant/id@version sha256:<digest>`，退出 0。
- 失败：stderr 输出 `invalid manifest: <原因>`，退出 1。
- 未知字段、非法 `id` / `version` / `tenant`、缺失必填字段都算失败。

## `adk-agent publish <path> [--registry DIR]`

校验 manifest，计算 digest，写入注册表。

- 成功：stdout 输出 `published tenant/id@version sha256:<digest>`，退出 0。
- 重复发布相同内容：幂等成功，返回已存记录。
- 同版本不同内容：stderr 输出 `publish failed: <原因>`，退出 1。
- 默认注册表目录是 `$ADK_REGISTRY_DIR`，否则 `./registry`。
- 存储布局是 `<registry>/<tenant>/<id>/<version>.json`。租户目录来自 manifest，不受调用方控制。

## `adk-agent new <name> [--template minimal] [--tenant TENANT]`

生成一个模板项目。

- `name` 和 `tenant` 都必须匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*$`。
- `--tenant` 默认 `local`，写入生成的 `manifest.json`。
- 生成 `agent.py`、`manifest.json`、`README.md`、`tests/test_agent.py`。
- 生成的 `manifest.json` 必须通过 `AgentManifest` 校验。
- `agent.py` 已存在时退出 1。
- 未知模板退出 1。
- 成功时逐行输出 `created <path>`，退出 0。

## `adk-agent console --agents FILE [--policy FILE] [--role ROLE]`

启动私有控制台。

- `--policy` 指向一个 `AccessPolicy` JSON 文件。给了才启用 RBAC 和 `/api/policy`。
- `--role` 可重复，设置控制台 principal 的角色。默认 `admin`。
- `GET /api/policy` 返回当前策略。`PUT /api/policy` 校验、原子落盘、热替换并写 `policy.update` 审计。
- 聊天按 `agent.run:<agent>` 检查策略。拒绝返回 403 `policy_denied`，并写 `agent.run` `denied` 审计。
- 没给 `--policy` 时控制台不做 RBAC，`/api/policy` 返回 404。

M1 的 `signature` 是 `sha256:<digest>` 完整性标记。它不是密钥签名，M4 会替换。
