# SLICE-013 模型网关（M1-2）

状态: gated
依据: ADR-0002 第 5、8 条

## 意图（要什么，不写怎么写）

所有模型调用经过一个网关。网关按 manifest 的 `ModelPolicy.provider_allowlist` 检查 provider，成功、拒绝、失败都写审计事件。

- `PolicyModelGateway` 负责策略和审计。
- `LiteLlmProvider` 接第三方模型，出口标记 `third_party`。
- `VllmProvider` 接本地 OpenAI 兼容端点，出口标记 `none`。
- 审计事件只存 hash、token、成本、延迟和出口标记，不存原始 prompt 或回复。
- `models` 从单文件改为包，收敛到 ADR-0002 的目录结构。`build_model` 的导入路径不变。

## 新增文件

- `src/adk_agent/core/model.py`
- `src/adk_agent/models/gateway.py`
- `src/adk_agent/models/providers.py`
- `tests/models/test_gateway.py`
- `tests/models/test_providers.py`

## 修改文件

- `src/adk_agent/models.py` -> `src/adk_agent/models/__init__.py`（移动）
- `src/adk_agent/core/ports.py`：`ModelProvider`、`ModelGateway`
- `src/adk_agent/core/__init__.py`：导出新区类型
- `.importlinter`：无需新增，`adk_agent.models` 已在禁止列表

## 完成判据（可执行）

- [x] 允许的 provider 返回响应并写 `ok` 审计事件 -> `tests/models/test_gateway.py::test_allowed_provider_is_audited`
- [x] 不在白名单的 provider 抛 `ModelDenied` 并写 `denied` 事件 -> `::test_unlisted_provider_is_denied_and_audited`
- [x] 白名单内但未配置的 provider 抛 `ModelDenied` -> `::test_unconfigured_provider_is_denied`
- [x] provider 异常写 `error` 事件并重新抛出 -> `::test_provider_error_is_audited_and_reraised`
- [x] provider key 与 `provider.name` 不一致时构造失败 -> `::test_provider_key_must_match_name`
- [x] LiteLLM 适配器构造正确请求并解析 token 与成本 -> `tests/models/test_providers.py::test_litellm_provider_builds_request`
- [x] vLLM 使用 `openai/` 前缀、`api_base`、`egress="none"` -> `::test_vllm_provider_is_local`
- [x] `from adk_agent.models import build_model` 仍然可用 -> `tests/test_smoke.py`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import ModelRequest` -> 当前不存在，`ImportError` -> gateway 测试收集失败
- [x] 反例 2：`from adk_agent.models.gateway import PolicyModelGateway` -> 当前不存在 -> `ModuleNotFoundError`
- [x] 反例 3：未授权 provider 调用 -> 当前无网关，期望 `ModelDenied` -> `test_unlisted_provider_is_denied_and_audited`
- [x] 反例 4：provider 抛异常 -> 期望审计 `error` 并重新抛出 -> `test_provider_error_is_audited_and_reraised`
- [x] 反例 5：LiteLLM 请求参数缺失 -> 期望 `model`、`messages`、`max_tokens`、`temperature` 都在 -> `test_litellm_provider_builds_request`

## 契约

### 模型调用类型

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class ModelRequest(BaseModel):
    provider: str
    model: str
    messages: list[Message]
    max_output_tokens: int | None = None
    temperature: float | None = None

class ModelResponse(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    egress: Literal["none", "third_party"]
```

### 端口

```python
class ModelProvider(Protocol):
    name: str
    egress: Literal["none", "third_party"]
    async def complete(self, request: ModelRequest) -> ModelResponse: ...

class ModelGateway(Protocol):
    async def complete(
        self, invocation: Invocation, request: ModelRequest, policy: ModelPolicy
    ) -> ModelResponse: ...
```

### 网关语义

- `request.provider` 不在 `policy.provider_allowlist`：写 `denied` 事件，`error_code="provider_not_allowed"`，抛 `ModelDenied`。
- 在白名单但网关没有该 provider：写 `denied` 事件，`error_code="provider_unavailable"`，抛 `ModelDenied`。
- provider 抛异常：写 `error` 事件，`error_code` 是异常类名，重新抛出。
- 成功：写 `ok` 事件，`tokens = input_tokens + output_tokens`，`cost_usd` 和 `egress` 来自响应和 provider。
- 审计事件 `action="model.call"`，`target="<provider>:<model>"`，`args_hash` 是消息 JSON 的 SHA-256，`result_hash` 是回复文本的 SHA-256，`latency_ms` 用单调时钟测量。
- 审计写入失败时调用失败。审计是治理的一部分，不静默跳过。

### 适配器

- `LiteLlmProvider(*, api_key=None, api_base=None)`：用 `litellm.acompletion`，`model=request.model`。
- `VllmProvider(base_url, *, api_key="not-needed")`：用 `litellm.acompletion`，`model=f"openai/{request.model}"`，`api_base=base_url`。
- 两者都惰性导入 `litellm`，未安装时只在调用时失败。

## 5 问威胁建模（10 分钟）

1. **数据**：prompt、回复、token、成本、provider 名、出口标记。
2. **调用方**：运行时、编排器。
3. **信任边界**：模型 provider 的响应、manifest 的 model policy。
4. **恶意输入最坏结果**：数据被发到策略不允许的 provider；成本无上限；prompt 被写进日志。白名单、出口标记、只存 hash 处理前两项和第三项。
5. **失败是否泄露信息**：审计事件不含 prompt 正文和回复正文，错误只含 provider、model 和异常类名。

## 证据

- 反例红: `pytest tests/models/test_gateway.py tests/models/test_providers.py -q` -> `ImportError: cannot import name 'ModelRequest' from 'adk_agent.core'`，两个测试模块收集失败
- 实现后绿: 目标测试 14 passed
- `check.py --fast` -> 78 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-013-model-gateway.txt`
