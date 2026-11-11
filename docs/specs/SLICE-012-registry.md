# SLICE-012 注册表与发布（M1-1）

状态: gated
依据: ADR-0002 第 3、9 条

## 意图（要什么，不写怎么写）

把 `AgentManifest` 变成可发布、可按 digest 拉取的不可变记录。

- `FileAgentRegistry` 实现 `AgentRegistry` 端口，一个 agent 版本一个 JSON 文件。
- 同一版本只能发布一次。内容相同视为幂等成功，内容不同报冲突。
- `get` 按 `id@version` 加 digest 拉取。digest 不匹配返回 `None`。文件被篡改时抛 `RegistryIntegrityError`。
- `adk-agent validate` 校验 manifest 并打印 digest。
- `adk-agent publish` 写入注册表。
- `AgentManifest` 和 `AgentRef` 的 `id`、`version` 限制为安全字符，阻止路径穿越。

M1 的 `signature` 是 `sha256:<digest>` 完整性标记，不是密钥签名。密钥签名在 M4 引入。这一点写进契约，不假装已经实现信任签名。

## 新增文件

- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/registry/file.py`
- `src/adk_agent/registry/manifest.py`
- `tests/registry/test_file_registry.py`
- `tests/test_registry_cli.py`
- `docs/contracts/cli.md`

## 修改文件

- `src/adk_agent/core/manifest.py`：`id`、`version` 安全字符校验。
- `src/adk_agent/cli.py`：`validate`、`publish` 子命令。
- `.importlinter`：`core` 禁止导入 `adk_agent.registry`。
- `docs/contracts/README.md`：登记 `cli.md`。
- `tests/core/test_contracts.py`：路径穿越反例。
- `docs/contracts/*.schema.json`：重新生成。

## 完成判据（可执行）

- [x] `AgentManifest(id="../evil")` 被拒绝 -> `tests/core/test_contracts.py::test_manifest_rejects_unsafe_id`
- [x] `AgentManifest(version="1/2")` 被拒绝 -> `::test_manifest_rejects_unsafe_version`
- [x] `AgentRef(id="../evil")` 被拒绝 -> `::test_agent_ref_rejects_unsafe_id`
- [x] 发布后可按 digest 取回 -> `tests/registry/test_file_registry.py::test_publish_then_get`
- [x] 重复发布相同内容幂等 -> `::test_publish_is_idempotent`
- [x] 同版本不同内容冲突 -> `::test_same_version_different_content_conflicts`
- [x] 不存在的版本返回 `None` -> `::test_get_missing_returns_none`
- [x] digest 不匹配返回 `None` -> `::test_wrong_digest_returns_none`
- [x] 文件被篡改抛 `RegistryIntegrityError` -> `::test_tampered_file_raises_integrity_error`
- [x] `signature == "sha256:<digest>"` -> `::test_signature_is_integrity_marker`
- [x] `validate` 成功打印 `id@version sha256:<digest>` -> `tests/test_registry_cli.py::test_validate_ok`
- [x] `validate` 遇到未知字段退出码 1 -> `::test_validate_rejects_unknown_field`
- [x] `publish` 写入注册表 -> `::test_publish_writes_registry`
- [x] `publish` 冲突退出码 1 -> `::test_publish_conflict_exits_one`

## 反例（必须在实现前跑红）

- [x] 反例 1：`id="../evil"` -> 当前接受，期望 `ValidationError` -> `test_manifest_rejects_unsafe_id`
- [x] 反例 2：`version="1/2"` -> 当前接受，期望 `ValidationError` -> `test_manifest_rejects_unsafe_version`
- [x] 反例 3：`from adk_agent.registry import FileAgentRegistry` -> 当前 `ModuleNotFoundError` -> registry 测试收集失败
- [x] 反例 4：同版本发布不同 description -> 当前无注册表，期望 `RegistryConflict` -> `test_same_version_different_content_conflicts`
- [x] 反例 5：篡改注册表文件 -> 期望 `RegistryIntegrityError` -> `test_tampered_file_raises_integrity_error`
- [x] 反例 6：`adk-agent validate` / `publish` -> 当前无子命令，`argparse` 退出 2 -> CLI 测试失败

## 契约

### 端口实现

```python
class FileAgentRegistry:
    def __init__(self, root: str | Path) -> None: ...
    async def get(self, ref: AgentRef) -> PublishedAgent | None: ...
    async def publish(self, agent: PublishedAgent) -> PublishedAgent: ...
```

存储布局：`<root>/<id>/<version>.json`，内容是 `PublishedAgent` 的 JSON。

### 发布语义

- 版本不可变。已存在且 digest 相同，返回已存记录。digest 不同，抛 `RegistryConflict`。
- 写入使用同目录临时文件加 `os.link` 原子创建，不覆盖已有文件。
- 读取时重新计算 manifest digest，与存储的 digest 不一致抛 `RegistryIntegrityError`。
- `get` 的 `ref.digest` 与存储 digest 不一致返回 `None`。

### 安全标识符

`id` 和 `version` 必须匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*\Z`。这排除 `/`、`\`、`..` 和以点开头的值。

### 签名

`published_from(manifest)` 生成 `signature = "sha256:<digest>"`。这是完整性标记，不是密钥签名。M4 替换为真正的签名方案。

### CLI

- `adk-agent validate <path>`：成功打印 `id@version sha256:<digest>`，退出 0；失败打印 `invalid manifest: ...` 到 stderr，退出 1。
- `adk-agent publish <path> [--registry DIR]`：成功打印 `published id@version sha256:<digest>`，退出 0；冲突或校验失败打印 `publish failed: ...`，退出 1。默认目录是 `$ADK_REGISTRY_DIR`，否则 `./registry`。

## 5 问威胁建模（10 分钟）

1. **数据**：manifest、digest、注册表文件。
2. **调用方**：CLI、后续运行时。
3. **信任边界**：manifest JSON、注册表目录。
4. **恶意输入最坏结果**：`id` 或 `version` 带路径分隔符写到目录外；注册表文件被篡改；同版本被静默覆盖。安全字符校验、读取时 digest 复核、`os.link` 不覆盖分别处理。
5. **失败是否泄露信息**：错误包含 id、version、digest，不包含 manifest 正文或密钥。

## 证据

- 反例红: 核心契约 3 failed（非法 id/version 被接受）；registry 测试 `ModuleNotFoundError`；CLI 测试 4 failed（`argparse` 无 `validate` / `publish`）
- 实现后绿: 目标测试 26 passed
- `check.py --fast` -> 71 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-012-registry.txt`
