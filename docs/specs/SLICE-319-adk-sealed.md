# SLICE-319 沙箱与工具守卫迁入适配层，墙归零（ADR-0046 切片 3c）

状态: active
依据: ADR-0046 已确认（2026-11-28）；3a（317）、3b（318）已合并，本切片收口

## 意图

最后 7 个模块迁入适配层，`google.adk` 只在 `adk_agent.adapters.adk` 出现：

- `sandbox.agent_channel`、`sandbox.agent_process`：`BaseLlm`/`LlmRequest`/`LlmResponse`
  改从 `adapters.adk.models` 取。
- `sandbox.agent_worker`：runner 与会话工厂改走适配层；最终文本改用
  `to_run_event` 提取，不再读 ADK 事件字段（补 2b 留下的沙箱缺口）。
- `sandbox.proxy`：`BaseAgent`/`InvocationContext`/`Event` 改从适配层取。
- `sandbox.runner`、`tools.guard`、`tools.enforcement`：`BaseTool`/`BaseToolset`/
  `BaseAgent` 改从适配层取。
- 墙的基线清零；SLICE-316 的事件扫描用例去掉 `sandbox/` 豁免。
- 新增 ADK 升级手册 `docs/guides/adk-upgrade.md`（ADR-0046 决定 5、6 的落地步骤）。

行为不变。

## 契约（先改）

- `adapters.adk.agents` 新增 `InvocationContext`；`adapters.adk.events` 新增 `Event`
  导出；`adapters.adk.tools` 新增 `BaseTool`、`BaseToolset`。
- 墙的基线为空集：`adk_wall.importers()` 只返回空字典。
- 无 HTTP / CLI 接口变化。

## 完成判据

- [ ] 适配层之外没有任何模块 import ADK -> `test_no_module_imports_adk_outside_the_adapter`
- [ ] 基线为空 -> `test_baseline_is_empty`
- [ ] 沙箱代码不再读 ADK 事件字段 -> 现有 `test_only_the_adapter_reads_adk_event_fields`（去掉豁免后仍通过）
- [ ] 升级手册覆盖演练、门禁与记录 -> `test_upgrade_runbook_covers_the_drill`
- [ ] `--full` 门禁通过

## 反例

实现前：基线仍是 7 项（`test_baseline_is_empty` 红）、`importers()` 非空（红）；
`adapters.adk.events.Event`、`adapters.adk.tools.BaseTool` 不存在（ImportError）；
升级手册不存在。

## 5 问威胁建模

1. **数据**：沙箱 worker 仍只拿输入文本，模型帧协议不变。
2. **调用方**：沙箱进程、工具守卫、A2A/MCP 入口。
3. **信任边界**：适配层是唯一碰 ADK 的目录，墙保证这一点。
4. **恶意输入**：无新增。
5. **失败是否泄露信息**：错误类型不变；worker 的事件文本提取与运行时同一条转换。

## 范围外

- 无（ADR-0046 到此收口）；后续 ADR-0047/0048 另开。

## 证据

- `docs/evidence/SLICE-319-adk-sealed.txt`
