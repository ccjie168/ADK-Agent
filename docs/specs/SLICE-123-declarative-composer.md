# SLICE-123 声明式组合器

状态: gated
依据: ADR-0022 决定 3 与 7。用户只选择受控模板并填写参数，平台生成 manifest 与 agent 代码，用平台侧发布密钥构建并签名工件，再走既有发布路径。用户不提交 Python、脚本或任意文件。

## 意图（要什么，不写怎么写）

给发布者一个 `compose` 命令。模板由平台代码定义，参数校验后生成确定性的 agent 工件，签名并发布成普通版本。

- 首期只有一个模板 `single-llm`：生成单 `LlmAgent`，支持可选的内置 `ping` 工具。
- 参数固定为 `name`、`version`、`tenant`、`owner`、`description`、`instruction`、`tools`、`data_classes`。未知参数拒绝。
- `name` 必须满足 ADK 命名，只允许字母、数字与下划线，避免生成后无法加载。
- `tools` 只能是模板声明的工具集合 `ping`。选中时 manifest 写同 id 的 `ToolGrant`，`data_classes` 进入授权与 `data_scopes`。
- 生成的代码只含平台模板文本。用户参数用 `repr` 嵌入，引号与换行不能逃逸成代码。
- 工件字节确定性：同参数同模板得到同一 digest。manifest JSON 排序，zip 时间戳固定。
- 发布走现有路径：`enforce_eval_gate`、`published_from`、注册表 `publish`、工件存储。生命周期默认 published，市场与加载规则不变。
- 签名密钥由操作员提供文件路径与 key id。平台不保存私钥，也不新增密钥托管。
- `templates` 命令列出模板与参数，供发现与校验。

## 数据形状

`src/adk_agent/compose/__init__.py`：

- `TemplateInfo`：`template_id`、`description`、`parameters`（名字、说明、必填、默认）与 `tools`。
- `list_templates() -> list[TemplateInfo]`。
- `build_composed(*, template_id, name, version, tenant, owner, description, instruction, tools, data_classes) -> tuple[AgentManifest, bytes]`。
- `async compose_and_publish(...)`：构建、签名、`published_from`、注册表发布、工件存储。HTTP 注册表走 `upload_artifact`。
- 错误：`ComposeError`、`UnknownTemplate`、`InvalidComposition`。

manifest 固定 `exposure="none"` 与 `model_policy.provider_allowlist=["litellm"]`，模板没有 `eval_suite`，因此评测门禁按既有规则放行。工件入口是 `agent.py`，同时导出 `root_agent`。

## 新增文件

- `src/adk_agent/compose/__init__.py`
- `tests/compose/test_declarative.py`
- `tests/compose/test_compose_publish.py`
- `tests/test_cli_compose.py`
- `docs/contracts/compose.md`
- `docs/evidence/SLICE-123-declarative-composer.txt`

## 修改文件

- `src/adk_agent/registry/packaging.py`（`pack_files`，`pack_agent` 复用）
- `src/adk_agent/registry/__init__.py`（导出 `pack_files`）
- `src/adk_agent/cli.py`（`compose` 与 `templates` 命令）
- `docs/contracts/cli.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [ ] 未知模板与未知参数被拒绝 -> `tests/compose/test_declarative.py::test_unknown_template_and_parameters_are_rejected`
- [ ] 带连字符或其他非法字符的 name 被拒绝 -> `::test_agent_name_must_be_adk_safe`
- [ ] 未声明的工具被拒绝 -> `::test_unknown_tool_is_rejected`
- [ ] 同参数生成同 digest，改 instruction 改变 digest -> `::test_composition_is_deterministic`
- [ ] instruction 中的引号与换行不能逃逸 -> `::test_instruction_cannot_escape_the_template`
- [ ] 组合结果可验签、可加载并带所选工具 -> `tests/compose/test_compose_publish.py::test_composed_agent_loads`
- [ ] 发布走评测门禁与注册表 -> `::test_compose_publishes_a_plain_version`
- [ ] CLI compose 与 templates -> `tests/test_cli_compose.py::test_cli_compose_and_templates`
- [ ] CLI 缺 key 或非法模板退出 1 -> `::test_cli_compose_errors`
- [ ] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [ ] 反例 1：模板接受带连字符的 name，加载时失败 -> 期望 `::test_agent_name_must_be_adk_safe` 失败
- [ ] 反例 2：instruction 直接插值，含三引号时破坏源码 -> 期望 `::test_instruction_cannot_escape_the_template` 失败
- [ ] 反例 3：字节不确定，重复组合 digest 不同 -> 期望 `::test_composition_is_deterministic` 失败
- [ ] 反例 4：compose 绕过签名或注册表直接写文件 -> 期望 `::test_compose_publishes_a_plain_version` 失败

红态记录: 待补，实现前运行。

## 5 问威胁建模（10 分钟）

1. **数据**：模板 id、agent 名、版本、租户、说明、instruction、工具选择与数据分级。
2. **调用方**：Agent 开发者或发布者，通过 CLI 提交参数，持有平台发布密钥的操作员运行 compose。
3. **信任边界**：用户参数到生成代码与 manifest；签名密钥到工件；工件到注册表与下载方。
4. **恶意输入最坏结果**：参数逃逸成任意代码（缓解：只用 `repr` 嵌入，模板文本固定，路径与文件名固定）；生成不可加载的 agent 名（缓解：ADK 命名校验）；伪造或替换签名（缓解：操作员密钥签名，加载方按信任库验签）；绕开评测与生命周期（缓解：复用 `enforce_eval_gate`、`published_from`、注册表 `publish`）；私钥进入仓库或日志（缓解：只从文件路径读取，错误不回显密钥内容）。
5. **失败是否泄露信息**：错误只含模板 id、参数名或错误类型，不含私钥、答案或生成字节。

## 范围外

- 控制台发布表单与 `/api/compose`。平台密钥不进入控制台进程，先由 CLI 承担。
- 密钥托管、轮换与审计。ADR-0022 已注明需要单独立项。
- 多模板目录、模板热加载、用户自定义模板。
- 评测套件生成与自动打分。模板没有 `eval_suite`，门禁按既有规则放行。
- 声明式工具授权审批。工具授权仍走现有 `ToolGrantRequest`。
- 从组合结果直接启动或热替换。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-123-declarative-composer.txt`
- 契约: `docs/contracts/compose.md`
