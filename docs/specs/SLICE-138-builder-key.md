# SLICE-138 构建密钥与 publish 默认层级

状态: gated
依据: ADR-0024 第 1 条与切片计划。ADR 要求代码发布默认 `sandboxed`，只有平台模板生成器可以声明 `in_process`。当前无法区分平台产物与手写 manifest。本切片引入平台构建密钥：`in_process` 工件必须带有效的 builder 签名，代码发布默认改为 `sandboxed`。

## 意图（要什么，不写怎么写）

1. `AgentArtifact` 增加 `builder_signature` 与 `builder_key_id`（128 hex / 安全 id），与发布者签名字段并列，digest 不变。
2. `TrustStore` 增加 `verify_builder(artifact)`：检查 builder 字段并用现有 keyring 校验 digest 签名。
3. `publish` 缺省 `execution_tier` 时按 `sandboxed` 处理（代码优先发布）；组合器与脚手架仍显式写 `in_process`。
4. `publish` 遇到 `in_process`：必须有工件，且 `builder_signature`/`builder_key_id` 能被 `--builder-keys`/`ADK_BUILDER_KEYS` 验证；否则退出 1。缺省翻成 `sandboxed` 后没有沙箱后端时按既有规则拒绝。
5. 组合器 `compose` 新增 `--builder-key`/`--builder-key-id`，签出 `in_process` 工件；缺省时组合器不再能发布 `in_process`。
6. `serve-registry` 的发布端点同样要求 `in_process` 工件带有效 builder 签名，用 `--builder-keys`/`ADK_BUILDER_KEYS`。
7. 加载路径不变：registry 记录已经过发布校验；本地 `--agents` 文件属运维信任域。

## 数据形状

- `AgentArtifact.builder_signature: str | None`（128 hex）、`builder_key_id: str | None`。
- 构建密钥对 digest 签名，算法与发布者签名相同；信任根格式复用 `TrustStore` JSON（key_id -> 64 hex）。

## 契约（先改）

- `docs/contracts/agent_artifact.schema.json`（导出）与 `docs/contracts/registry_service.md`、`docs/contracts/cli.md`。
- `docs/contracts/manifest.schema.json` 的门禁说明：缺省按 `sandboxed`。

## 新增/修改文件

- `src/adk_agent/core/artifact.py`、`registry/trust.py`、`registry/service.py`、`compose/__init__.py`、`cli.py`
- 测试：`tests/registry/test_builder_key.py`、`tests/compose/test_compose.py`、`tests/test_cli_publish_tier.py`、`tests/test_registry_service.py`
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-138-builder-key.txt`

## 完成判据（可执行）

- [x] `in_process` 工件缺 builder 签名时发布退出 1 -> `test_publish_in_process_requires_a_builder_signature`
- [x] 用可信 builder 密钥签名的 `in_process` 工件可发布 -> `test_publish_in_process_accepts_a_trusted_builder`
- [x] 缺省 tier 按 `sandboxed` 处理 -> `test_publish_defaults_to_sandboxed`
- [x] 组合器输出带 builder 签名且可发布 -> `tests/compose/test_compose_publish.py`
- [x] 注册表服务拒绝无 builder 签名的 `in_process` 发布 -> `test_publish_in_process_rejects_a_missing_builder_signature`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（实现前跑红）

- [x] 反例 1：当前 `in_process` 工件无需 builder 签名即可发布 -> 期望 `test_publish_in_process_requires_builder_signature` 失败
- [x] 反例 2：当前缺省 tier 被拒而不是按 `sandboxed` -> 期望 `test_publish_defaults_to_sandboxed` 失败

## 5 问威胁建模

1. **数据**：工件 digest、构建签名、发布者签名、builder keyring。
2. **调用方**：发布者、注册表服务、组合器。
3. **信任边界**：平台构建密钥与发布者密钥分离。
4. **恶意输入最坏结果**：手写 manifest 冒充平台产物（缓解：builder 签名）；重放他人签名（缓解：签名绑定 digest）；builder 密钥泄露（缓解：轮换与 key id，另行运维）。
5. **失败是否泄露信息**：只回稳定错误，不回显密钥材料。

## 范围外

- builder 密钥轮换、吊销与 HSM/KMS 托管。
- 组合模板的安全评审流程本身。
- 既有已发布 `in_process` 记录的回填；按 ADR 兼容策略读取，不重签。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-138-builder-key.txt`
