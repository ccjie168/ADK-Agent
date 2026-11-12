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

M1 的 `signature` 是 `sha256:<digest>` 完整性标记。它不是密钥签名，M4 会替换。
