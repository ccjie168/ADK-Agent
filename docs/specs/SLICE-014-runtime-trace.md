# SLICE-014 运行时注入（M1-3）

状态: gated
依据: ADR-0002 第 4、6 条

## 意图（要什么，不写怎么写）

把一次 agent 调用变成可追溯的 run。

- `AgentRuntime` 包装 ADK `Runner`，把 `run_id`、`trace_id`、`principal`、`agent_ref` 写进 `RunConfig.custom_metadata`。
- 收集最终回复，过滤 thought 片段。
- 成功和失败都写 `agent.run` 审计事件。
- 控制台改用运行时，响应返回 `run_id` 和 `trace_id`，并接受 `X-Trace-Id` 请求头。
- `InvocationResult` 承载 run 身份和回复文本。

模型层的网关接入不在这一刀。ADK 的 `LlmAgent` 自己驱动模型循环，把 `ModelGateway` 接进去需要自定义模型适配或回调，放到后续切片。这一刀只保证 run 级 trace 和审计。

## 新增文件

- `src/adk_agent/runtime/__init__.py`
- `src/adk_agent/runtime/execution.py`
- `tests/runtime/test_execution.py`

## 修改文件

- `src/adk_agent/core/invocation.py`：`InvocationResult`
- `src/adk_agent/core/__init__.py`：导出 `InvocationResult`
- `src/adk_agent/console.py`：使用 `AgentRuntime`，返回 run_id / trace_id
- `.importlinter`：`core` 禁止导入 `adk_agent.runtime`
- `tests/test_console_hardening.py`：trace 头测试

## 完成判据（可执行）

- [x] `run_async` 收到 `custom_metadata`，含 run_id、trace_id、principal、agent_ref -> `tests/runtime/test_execution.py::test_run_injects_trace_metadata`
- [x] 最终回复只收非 thought 文本 -> `::test_run_filters_thought_parts`
- [x] 成功写 `agent.run` `ok` 审计 -> `::test_run_is_audited`
- [x] 失败写 `error` 审计并重新抛出 -> `::test_run_error_is_audited_and_reraised`
- [x] `new_message` 使用 invocation 输入 -> `::test_run_uses_invocation_input`
- [x] 控制台响应含 `run_id` 和 `trace_id`，并接受 `X-Trace-Id` -> `tests/test_console_hardening.py::test_chat_returns_trace_ids`
- [x] 现有控制台错误日志测试继续通过 -> `::test_chat_failure_is_logged`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.runtime import AgentRuntime` -> 当前 `ModuleNotFoundError` -> runtime 测试收集失败
- [x] 反例 2：`custom_metadata` 缺失 -> 当前无运行时，期望四个键 -> `test_run_injects_trace_metadata`
- [x] 反例 3：thought 片段混入回复 -> 期望被过滤 -> `test_run_filters_thought_parts`
- [x] 反例 4：runner 抛异常 -> 期望审计 `error` 并重新抛出 -> `test_run_error_is_audited_and_reraised`
- [x] 反例 5：控制台响应无 trace_id -> 期望返回 -> `test_chat_returns_trace_ids`

## 契约

### InvocationResult

```python
class InvocationResult(BaseModel):
    run_id: str
    trace_id: str
    agent_ref: AgentRef
    text: str
```

### AgentRuntime

```python
class AgentRuntime:
    def __init__(self, runner: Any, audit: AuditSink | None = None) -> None: ...
    async def run(
        self, invocation: Invocation, *, user_id: str, session_id: str
    ) -> InvocationResult: ...
```

- `RunConfig.custom_metadata` 的键：`run_id`、`trace_id`、`principal`（JSON dict）、`agent_ref`（JSON dict）。
- `new_message` 是 `types.Content(role="user", parts=[types.Part(text=invocation.input)])`。
- 只收集 `event.is_final_response()` 且 `part.thought` 为假的文本。
- 成功：写 `agent.run` 事件，`status="ok"`，`args_hash` 是输入 SHA-256，`result_hash` 是回复 SHA-256，`egress="none"`。
- 失败：写 `status="error"` 事件，`error_code` 是异常类名，然后重新抛出。
- 审计 sink 为 `None` 时跳过审计，不改变行为。

### 控制台

- 每个 agent 构造一个 `AgentRuntime`。
- `dev_agent_ref(name)`：`version="dev"`，`digest=sha256(name)`。控制台的 agent 未发布，用 dev ref 明确标记。
- `principal = Principal(tenant="local", subject="console_user", kind="human")`。
- `trace_id` 取 `X-Trace-Id`，只接受 `^[A-Za-z0-9._-]{1,128}$`；否则生成 UUID。
- 响应增加 `run_id` 和 `trace_id`。

## 5 问威胁建模（10 分钟）

1. **数据**：用户输入、agent 回复、principal、trace id。
2. **调用方**：控制台、后续编排器。
3. **信任边界**：HTTP `X-Trace-Id` 头、agent 输出。
4. **恶意输入最坏结果**：trace 头带换行或超长内容污染日志和审计。白名单正则和长度上限处理。
5. **失败是否泄露信息**：审计只存输入和输出的 hash，不存正文；错误只含异常类名。

## 证据

- 反例红: runtime 测试 `ModuleNotFoundError: No module named 'adk_agent.runtime'`；控制台新测试 `KeyError: 'trace_id'`
- 实现后绿: 目标测试 16 passed
- `check.py --fast` -> 84 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-014-runtime-trace.txt`
