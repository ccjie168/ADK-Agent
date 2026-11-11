# SLICE-017 模型网关接入（M1-5b）

状态: gated
依据: ADR-0002 第 4、5、8 条

## 意图（要什么，不写怎么写）

把 `PolicyModelGateway` 真正接进 ADK 的模型循环。

- 新增 `GatewayLlm(BaseLlm)`，包装原 ADK 模型。
- 它从 contextvar 读取当前 `Invocation`，检查 `ModelPolicy.provider_allowlist`，然后委托原模型执行。
- 成功、拒绝、失败都写 `model.call` 审计事件，带 token、出口标记和 hash。
- 原模型的工具、配置和流式行为不变，因为 `GatewayLlm` 只做策略和审计，不重建请求。
- 控制台在构建 Runner 前包装每个 `LlmAgent` 的 `BaseLlm` 模型。

范围限制，写清楚。

- 控制台里的 agent 没有发布 manifest，dev 策略由模型 provider 推导，因此是“总是允许当前 provider”的宽松策略。真正的白名单要等控制台加载已发布 manifest。
- MCP `serve_agent` 路径还没有接网关。它走 ADK 自己的 runner，不在本切片范围。

## 新增文件

- `src/adk_agent/core/context.py`
- `src/adk_agent/models/gateway_llm.py`
- `tests/models/test_gateway_llm.py`
- `tests/test_console_gateway.py`

## 修改文件

- `src/adk_agent/models/gateway.py`：抽出 `check_provider`、`emit_model_audit`、`egress_for`
- `src/adk_agent/runtime/execution.py`：设置和重置 invocation contextvar
- `src/adk_agent/console.py`：包装 `BaseLlm` 模型
- `.importlinter`：无需新增，`models` 和 `runtime` 都只依赖 `core`

## 完成判据（可执行）

- [x] `GatewayLlm` 委托原模型并写 `model.call` `ok` 事件 -> `tests/models/test_gateway_llm.py::test_delegates_and_audits`
- [x] token 来自 usage metadata，egress 按 provider 标记 -> `::test_delegates_and_audits`
- [x] provider 不在白名单时抛 `ModelDenied`，写 `denied` 事件，且不调用原模型 -> `::test_denied_provider_is_not_called`
- [x] 没有 invocation 上下文时抛 `ModelDenied` -> `::test_requires_invocation_context`
- [x] 原模型异常写 `error` 事件并重新抛出 -> `::test_delegate_error_is_audited`
- [x] 控制台把 `BaseLlm` 模型换成 `GatewayLlm` -> `tests/test_console_gateway.py::test_console_wraps_base_llm`
- [x] 现有 96 个测试继续通过 -> `check.py --fast`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.models.gateway_llm import GatewayLlm` -> 当前 `ModuleNotFoundError` -> 测试收集失败
- [x] 反例 2：未授权 provider 仍调用原模型 -> 期望 `ModelDenied` 且原模型未被调用 -> `test_denied_provider_is_not_called`
- [x] 反例 3：没有 invocation 上下文仍调用原模型 -> 期望拒绝 -> `test_requires_invocation_context`
- [x] 反例 4：原模型异常没有审计 -> 期望 `error` 事件 -> `test_delegate_error_is_audited`
- [x] 反例 5：控制台不包装模型 -> `agent.model` 不是 `GatewayLlm` -> `test_console_wraps_base_llm`

## 契约

### contextvar

```python
def current_invocation() -> Invocation | None: ...
def set_invocation(invocation: Invocation) -> Token[Invocation | None]: ...
def reset_invocation(token: Token[Invocation | None]) -> None: ...
```

`AgentRuntime.run` 在进入模型循环前设置，在 `finally` 重置。

### GatewayLlm

```python
class GatewayLlm(BaseLlm):
    delegate: BaseLlm
    provider: str
    policy: ModelPolicy
    audit: Any | None = None

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]: ...
```

- 没有 `current_invocation()` 时抛 `ModelDenied`，fail closed。
- provider 不在 `policy.provider_allowlist` 时写 `denied` 事件，`error_code="provider_not_allowed"`，抛 `ModelDenied`。
- 原模型异常写 `error` 事件，`error_code` 是异常类名，重新抛出。
- 成功写 `ok` 事件，`args_hash` 是 `llm_request.contents` 的规范 JSON SHA-256，`result_hash` 是最终响应文本的 SHA-256，`tokens` 来自 `usage_metadata`，`cost_usd=None`，`egress` 按 provider。
- 流式场景只审计最后一个响应，token 以最后一个响应的 usage 为准。这是 M1 的近似，写在注释和 spec 里。

### provider 与 egress

```python
def provider_for_model(model: BaseLlm) -> str: ...
def egress_for(provider: str) -> Literal["none", "third_party"]: ...
```

类名映射：`Gemini` -> `gemini`，`AnthropicLlm` -> `claude`，`LiteLlm` -> `litellm`，`Claude` -> `vertex`。`vllm` -> `none`，其余 -> `third_party`。

### 控制台

- 只包装 `isinstance(agent.model, BaseLlm)` 的 agent。字符串模型交给 ADK 自己解析，本切片不包装。
- 递包子 agent。
- dev 策略是 `ModelPolicy(provider_allowlist=[provider])`。它保证调用经过网关和审计，但不是真正的最小权限。白名单要等 manifest 驱动的控制台。

## 5 问威胁建模（10 分钟）

1. **数据**：prompt、响应、token、provider、出口标记。
2. **调用方**：ADK `LlmAgent`，由 `AgentRuntime` 驱动。
3. **信任边界**：模型 provider 响应、manifest 的 model policy。
4. **恶意输入最坏结果**：模型调用绕过白名单或审计。contextvar 缺失时拒绝，provider 不在白名单时拒绝，审计 sink 失败时调用失败。
5. **失败是否泄露信息**：审计只存 hash 和元数据；错误只含 provider、model 和异常类名。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.models.gateway_llm'`，两个测试模块收集失败
- 实现后绿: 目标测试 21 passed
- `check.py --fast` -> 103 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-017-gateway-wiring.txt`
