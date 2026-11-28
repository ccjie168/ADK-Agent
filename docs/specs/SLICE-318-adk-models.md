# SLICE-318 模型与工具源迁入适配层（ADR-0046 切片 3b）

状态: active
依据: ADR-0046 已确认（2026-11-28）；切片 3 拆成 3a（加载/触发）已合并、
3b（本切片）、3c（沙箱与工具守卫）

## 意图

`models`、`models.gateway_llm`、`mcp.client`、`tools.sources` 不再直接 import ADK：

- `adapters.adk.models`：`BaseLlm`、`LlmRequest`、`LlmResponse` 类型导出，以及
  `gemini_model`/`claude_llm`/`vertex_claude`/`litellm_model` 四个惰性构造器
  （依赖各自 provider 的可选包，保持按需导入）。
- `adapters.adk.mcp_tools`：`mcp_toolset`、`stdio_params`、`http_params`。
- `adapters.adk.tools`：`openapi_toolset`。

模型选择逻辑（provider → 类、key 注入方式）不变，网关包装与策略审计不变。

## 契约（先改）

- 新增 `adapters.adk.models`、`adapters.adk.mcp_tools`、`adapters.adk.tools` 三个
  （或合并为一个 `tools.py`）模块，从 `adapters.adk` 包导出。
- 无 HTTP / CLI 接口变化；`build_model` 的返回类型仍是 ADK `BaseLlm` 子类。
- 墙的基线从 11 项减到 7 项：`sandbox.*`（5 个）、`tools.enforcement`、`tools.guard`。

## 完成判据

- [ ] 四个模块不再 import ADK -> `test_model_and_tool_modules_leave_the_wall`
- [ ] 基线只剩沙箱与工具守卫 -> `test_baseline_is_sandbox_and_guards`
- [ ] 模型构造器仍返回 ADK 模型 -> `test_model_builders_return_adk_models`
- [ ] MCP 工具集构造走适配层 -> `test_mcp_toolset_builds_through_the_adapter`
- [ ] OpenAPI 工具集构造走适配层 -> `test_openapi_toolset_builds_through_the_adapter`
- [ ] `--full` 门禁通过

## 反例

实现前：四个模块仍在基线里（红）、基线是 11 项（红）；`adapters.adk.models` 等模块
不存在（ImportError）。

## 5 问威胁建模

1. **数据**：模型 API key 只在构造客户端时使用，路径不变。
2. **调用方**：`factory.build_agent`、模型网关、`serve-model-gateway`。
3. **信任边界**：仍是同一批 ADK 类；新增的只是转发函数。
4. **恶意输入**：无新增；OpenAPI 文档解析逻辑不变。
5. **失败是否泄露信息**：错误类型不变（缺可选依赖仍是 `ImportError`）。

## 范围外

- 沙箱与工具守卫（3c）、ADK 升级手册（3c 收尾）。

## 证据

- `docs/evidence/SLICE-318-adk-models.txt`
