# SLICE-314 ADK 导入墙与兼容演练（ADR-0046 切片 1）

状态: active
依据: ADR-0046 已确认（2026-11-28），切片 2 同意拆成 2a/2b

## 意图

先把墙立起来，不改任何行为：

1. 新增 `adk_agent.adapters.adk` 包，作为唯一允许 import `google.adk` 的目录。
2. `scripts/adk_wall.py` 用 AST 扫描真实的 `google.adk` import；现有 20 个导入方进
   基线白名单，只能减少、不能新增；`scripts/check_layering.py` 把它接进门禁的 layering 步。
3. `scripts/adk_compat.py` 检查被依赖的 ADK 面（Runner 签名、Event 字段、`_mcp`、
   `_agent_to_mcp`、A2A 执行器类），漂移即红。
4. 新增 `AgentRuntime` 端口（`load`、`run`），为 2a 的迁移定契约。

## 契约（先改）

- `core.AgentRuntime`：`load(path) -> Any`、`async run(agent, invocation) -> InvocationResult`。
- `scripts/adk_wall.py` 的基线是 20 个模块；`adapters.adk` 及其子模块不受限。
- `scripts/adk_compat.py` 五项检查全部 PASS 才算通过。

## 完成判据

- [ ] 没有墙外的 ADK 导入方 -> `test_adk_wall_has_no_unlisted_importers`
- [ ] 基线白名单与现状一致（新增导入会让它红） -> `test_adk_wall_baseline_matches_reality`
- [ ] 适配包是唯一豁免 -> `test_adapter_package_is_the_only_allowed_importer`
- [ ] 兼容演练通过 -> `test_adk_compat_drill_passes`
- [ ] 端口已导出 -> `test_agent_runtime_port_is_exported`
- [ ] `from google import adk` 也被墙捕获 -> `test_adk_wall_catches_parent_package_import`
- [ ] `--full` 门禁通过

## 反例

实现前没有 `adapters` 包、`adk_wall.py`、`adk_compat.py` 与 `AgentRuntime`；
五条用例全部 `ImportError` 或断言失败。墙本身在实现前也不存在，任何模块都能 import ADK。

## 5 问威胁建模

1. **数据**：无业务数据；脚本只读源码与 ADK 元数据。
2. **调用方**：CI 与本地门禁。
3. **信任边界**：AST 扫描只看 import 语句，不看字符串；`google.genai` 不在墙内。
4. **恶意输入**：不执行被扫描文件，只解析。
5. **失败是否泄露信息**：失败只打印模块名。

## 范围外

- 迁移入口与事件（0046-2a/2b）。
- import-linter 的契约扩展（现有 `core` 隔离契约不变；墙由 AST 脚本承担）。

## 证据

- `docs/evidence/SLICE-314-adk-wall.txt`
