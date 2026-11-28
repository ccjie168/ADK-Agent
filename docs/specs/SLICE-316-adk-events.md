# SLICE-316 事件边界（ADR-0046 切片 2b）

状态: active
依据: ADR-0046 已确认（2026-11-28），切片 2 拆成 2a/2b

## 意图

定义平台的运行事件类型 `RunEvent`/`RunPart`，在适配层一次性把 ADK `Event` 转成平台
类型；上层（`runtime.execution`、`runtime.audit_proxy`）不再读 ADK 事件的
`is_final_response()`、`content.parts`、`function_call` 等字段。MCP/A2A 出口仍向 ADK
转发原始事件，行为不变。

## 契约（先改）

- `core.RunEvent(author, final, parts)`、`core.RunPart(kind, text, name)`，
  `kind ∈ {text, tool_call, tool_result}`；`RunEvent.text` 为文本片段拼接。
- 新增 `docs/contracts/run_event.schema.json`（由 `scripts/export_contracts.py` 生成）。
- `adapters.adk.events.to_run_event(event) -> RunEvent` 是唯一转换点，幂等
  （传入 `RunEvent` 原样返回）。
- MCP/A2A 的 `run_async` 仍然产出 ADK 原始事件；只有平台自己的进度与结果提取改用
  `RunEvent`。

## 完成判据

- [ ] 文本、工具调用、工具结果都被提取 -> `test_run_event_conversion_extracts_parts`
- [ ] 思考片段被丢弃 -> `test_run_event_drops_thought_parts`
- [ ] 运行时可消费纯平台事件 -> `test_agent_runtime_consumes_platform_events`
- [ ] 审计代理用平台事件取最终文本 -> `test_audit_proxy_extracts_final_text_from_run_events`
- [ ] 适配层之外不再读 ADK 事件字段 -> `test_only_the_adapter_reads_adk_event_fields`
- [ ] `--full` 门禁通过

## 反例

实现前：`core.RunEvent` 与 `adapters.adk.events` 不存在（ImportError）；给运行时喂
`RunEvent` 会因 `event.is_final_response()` 缺失抛 `AttributeError`；源码扫描会命中
`runtime/execution.py`、`runtime/audit_proxy.py` 里的 ADK 字段读取。

`sandbox/` 不在本切片：它属于 0046-3，扫描用例暂时排除该目录并在证据里写明。

## 5 问威胁建模

1. **数据**：事件文本进入进度事件与审计哈希，路径不变。
2. **调用方**：控制台 SSE、审计代理、评估命令。
3. **信任边界**：转换在适配层；上层只看到 `RunEvent`。
4. **恶意输入**：事件字段缺失或为 `None` 时转换给出空片段，不抛异常。
5. **失败是否泄露信息**：不新增错误类型。

## 范围外

- `sandbox/` 的事件读取（0046-3）。
- 加载与组合迁移（0046-3）。

## 证据

- `docs/evidence/SLICE-316-adk-events.txt`
