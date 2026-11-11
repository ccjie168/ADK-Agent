# SLICE-015 基础模板（M1-4）

状态: gated
依据: ADR-0002 第 3、9 条

## 意图（要什么，不写怎么写）

把 `adk-agent new` 从单文件脚手架升级为模板生成器。

- `BuiltinTemplateSource` 实现 `TemplateSource` 端口。
- `minimal` 模板生成四个文件：`agent.py`、`manifest.json`、`README.md`、`tests/test_agent.py`。
- `manifest.json` 必须通过 `AgentManifest` 校验。
- `adk-agent new <name> [--template minimal]` 写入这些文件。
- 拒绝已存在的 `agent.py`、非法名字、未知模板。

模板是版本化产物，不是文档。生成器保证每个新项目都有可校验的 manifest 和冒烟测试。

## 新增文件

- `src/adk_agent/templates/__init__.py`
- `src/adk_agent/templates/builtin.py`
- `tests/templates/test_builtin.py`
- `tests/test_new_cli.py`

## 修改文件

- `src/adk_agent/cli.py`：`new` 使用模板生成器，增加 `--template`
- `docs/contracts/cli.md`：补充 `new`
- `.importlinter`：`core` 禁止导入 `adk_agent.templates`

## 完成判据（可执行）

- [x] `minimal` 渲染出四个文件 -> `tests/templates/test_builtin.py::test_render_minimal_project`
- [x] 渲染的 manifest 通过 `AgentManifest` 校验 -> `::test_rendered_manifest_is_valid`
- [x] 未知模板抛 `TemplateNotFound` -> `::test_unknown_template_is_rejected`
- [x] 非法名字被拒绝 -> `::test_unsafe_name_is_rejected`
- [x] `adk-agent new` 写入四个文件 -> `tests/test_new_cli.py::test_new_creates_project`
- [x] 已存在 `agent.py` 时退出码 1 -> `::test_new_refuses_existing_agent`
- [x] 非法名字在创建目录前被拒绝 -> `::test_new_rejects_unsafe_name`
- [x] 未知模板退出码 1 -> `::test_new_rejects_unknown_template`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.templates import BuiltinTemplateSource` -> 当前 `ModuleNotFoundError` -> 模板测试收集失败
- [x] 反例 2：`adk-agent new` 只生成 `agent.py`，没有 `manifest.json` -> 期望四个文件 -> `test_new_creates_project`
- [x] 反例 3：`new ../evil` 当前会创建目录 -> 期望在创建前拒绝 -> `test_new_rejects_unsafe_name`
- [x] 反例 4：未知模板当前被忽略 -> 期望 `TemplateNotFound` / 退出 1 -> `test_new_rejects_unknown_template`

## 契约

### TemplateSource

```python
class TemplateSource(Protocol):
    async def render(
        self, template_id: str, params: Mapping[str, str]
    ) -> Mapping[str, str]: ...
```

`BuiltinTemplateSource.render` 返回相对路径到内容的映射。`minimal` 接受 `params["name"]`。

### 生成物

- `agent.py`：`LlmAgent`，一个 `ping` 工具，`agent` 和 `root_agent` 两个别名。
- `manifest.json`：`id=name`，`version="0.1.0"`，`owner="change-me"`，`model_policy.provider_allowlist=["litellm"]`，`tool_grants=[{"tool_id": "ping", "data_classes": ["internal"]}]`，`data_scopes=["internal"]`，`exposure="none"`。
- `README.md`：validate、publish、run 三步，并提示设置模型通道。
- `tests/test_agent.py`：导入 `agent` 并断言名字。

### CLI

`adk-agent new <name> [--template minimal]`

- 名字必须匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*$`，在创建任何目录前校验。
- `agent.py` 已存在时退出 1。
- 未知模板退出 1。
- 成功时逐行打印 `created <path>`，退出 0。

## 5 问威胁建模（10 分钟）

1. **数据**：模板参数、生成的文件内容。
2. **调用方**：开发者、后续 CLI。
3. **信任边界**：`new` 的名字参数来自命令行。
4. **恶意输入最坏结果**：`../evil` 把文件写到项目外。安全字符校验在 `Path` 和 `mkdir` 之前执行。
5. **失败是否泄露信息**：错误只回显非法名字或模板名，不包含文件内容或密钥。

## 证据

- 反例红: templates 测试 `ModuleNotFoundError`；CLI 测试 4 failed（缺 manifest、非法名字未拒绝、未知模板退出 2、已存在 agent 退出码非 1）
- 实现后绿: 目标测试 8 passed
- `check.py --fast` -> 92 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-015-templates.txt`
