# SLICE-317 加载与触发服务迁入适配层（ADR-0046 切片 3a）

状态: active
依据: ADR-0046 已确认（2026-11-28）。切片 3 按依赖面拆成 3a（加载/触发）、
3b（模型与工具源）、3c（沙箱与工具守卫），每段单独验证，墙的基线逐段缩短。

## 意图

`factory.py`、`registry/loader.py`、`triggers_service.py` 不再直接 import ADK：

- `factory`：`LlmAgent` 由 `adapters.adk.agents` 提供，`Runner` 改用
  `adapters.adk.runner.make_runner`。
- `registry/loader.py`：加载后对 `BaseAgent` 的 isinstance 检查改用适配层类型。
- `triggers_service`：内存 session 与 `Runner` 改走适配层工厂。

行为不变；这三处都是构造与类型检查，没有语义改动。

## 契约（先改）

- `adapters.adk.agents` 新增导出 `LlmAgent`（与已有 `BaseAgent` 并列）。
- 无 HTTP / CLI 接口变化。
- 墙的基线从 14 项减到 11 项：只剩 `models`、`models.gateway_llm`、`mcp.client`、
  `sandbox.*`（6 个）、`tools.enforcement`、`tools.guard`、`tools.sources`。

## 完成判据

- [ ] 三个模块不再 import ADK -> `test_loading_modules_leave_the_wall`
- [ ] 基线只剩模型、工具源与沙箱 -> `test_baseline_is_models_tools_and_sandbox`
- [ ] 源码里也不再出现 `google.adk` 字样 -> `test_loading_modules_have_no_adk_text`
- [ ] 构建出的 agent 仍是 ADK `BaseAgent` -> `test_build_agent_returns_an_adk_agent`
- [ ] `build_runner` 返回真 `Runner` -> `test_build_runner_uses_the_adapter_runner`
- [ ] `--full` 门禁通过

## 反例

实现前：三个模块仍在基线里（`test_loading_modules_leave_the_wall` 红）、基线是 14 项
（红）、三个文件里仍有 `google.adk` 字样（红）；`LlmAgent` 尚未从适配层导出
（ImportError）。

## 5 问威胁建模

1. **数据**：无新增数据面。
2. **调用方**：`adk-agent serve/serve-triggers/console` 的启动路径。
3. **信任边界**：仍是同一批 ADK 构造调用，只是经适配层转手。
4. **恶意输入**：无。
5. **失败是否泄露信息**：错误类型不变。

## 范围外

- 模型与工具源（3b）、沙箱与工具守卫（3c）、ADK 升级手册（3c 收尾）。

## 证据

- `docs/evidence/SLICE-317-adk-loading.txt`
