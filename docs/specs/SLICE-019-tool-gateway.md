# SLICE-019 工具网关与策略（M2-1）

状态: gated
依据: ADR-0002 第 5、6 条

## 意图（要什么，不写怎么写）

建立工具调用的统一入口。

- `FunctionRegistry` 注册本地函数工具，带 tool_id、数据分级、是否需要审批。
- `GrantPolicyEngine` 按 agent 的 `ToolGrant` 决定放行或拒绝。
- `FunctionToolGateway` 检查策略、调用函数、写 `tool.call` 审计。
- 未注册工具、策略拒绝、需要审批、函数异常都拒绝或记录，不静默通过。

这一刀只做网关组件和测试。把它接进 ADK 的工具循环是 SLICE-020，不让本切片假装已经覆盖 agent 的实际工具调用。

## 新增文件

- `src/adk_agent/core/tool.py`
- `src/adk_agent/tools/__init__.py`
- `src/adk_agent/tools/registry.py`
- `src/adk_agent/tools/policy.py`
- `src/adk_agent/tools/gateway.py`
- `tests/tools/test_policy.py`
- `tests/tools/test_tool_gateway.py`

## 修改文件

- `src/adk_agent/core/ports.py`：`ToolGateway`
- `src/adk_agent/core/__init__.py`：导出 `ToolRequest`、`ToolResponse`、`ToolGateway`
- `src/adk_agent/audit/hashing.py`：从 `models/gateway.py` 抽出 `hash_text`、`hash_json`
- `src/adk_agent/models/gateway.py`：改用共享 hash
- `src/adk_agent/models/gateway_llm.py`：改用共享 hash
- `.importlinter`：`core` 禁止导入 `adk_agent.tools`
- `docs/specs/ROADMAP.md`：M2 切片

## 完成判据（可执行）

- [x] 已授权工具返回结果并写 `tool.call` `ok` 事件 -> `tests/tools/test_tool_gateway.py::test_allowed_tool_is_audited`
- [x] 未授权工具抛 `ToolDenied`，不调用函数，写 `denied` 事件 -> `::test_denied_tool_is_not_called`
- [x] 未注册工具被拒绝，`error_code="tool_unavailable"` -> `::test_unknown_tool_is_denied`
- [x] 函数异常写 `error` 事件并重新抛出 -> `::test_handler_error_is_audited`
- [x] 需要审批的工具被拒绝，`error_code="approval_required"` -> `::test_requires_approval_is_denied`
- [x] 异步函数被正确等待 -> `::test_async_handler`
- [x] 审计带数据分级、参数 hash、结果 hash -> `::test_allowed_tool_is_audited`
- [x] 重复 tool_id 在注册时被拒绝 -> `::test_duplicate_tool_ids_rejected`
- [x] 授权策略放行已 grant 的工具，拒绝其他 -> `tests/tools/test_policy.py`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools import FunctionToolGateway` -> 当前 `ModuleNotFoundError` -> 测试收集失败
- [x] 反例 2：未授权工具仍被调用 -> 期望 `ToolDenied` 且函数未被调用 -> `test_denied_tool_is_not_called`
- [x] 反例 3：未注册工具直接执行 -> 期望拒绝 -> `test_unknown_tool_is_denied`
- [x] 反例 4：函数异常没有审计 -> 期望 `error` 事件 -> `test_handler_error_is_audited`
- [x] 反例 5：需要审批的工具直接执行 -> 期望拒绝 -> `test_requires_approval_is_denied`

## 契约

### 数据形状

```python
class ToolRequest(BaseModel):
    tool_id: str
    args: dict[str, Any] = {}

class ToolResponse(BaseModel):
    output: Any
    data_classes: list[DataClass] = []

class ToolGateway(Protocol):
    async def invoke(
        self, invocation: Invocation, request: ToolRequest, policy: PolicyEngine
    ) -> ToolResponse: ...
```

### 注册与策略

```python
@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    handler: Callable[..., Any]
    data_classes: tuple[DataClass, ...] = ()
    requires_approval: bool = False

class FunctionRegistry:
    def __init__(self, tools: list[ToolSpec]) -> None: ...
    def get(self, tool_id: str) -> ToolSpec | None: ...

class GrantPolicyEngine:
    def __init__(self, grants: list[ToolGrant]) -> None: ...
    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision: ...
```

`GrantPolicyEngine` 对 `action="tool.call"` 且 target 在 grants 中返回 allow，否则 deny。policy_version 是 `grants-v1`。

### 网关语义

- 未注册：写 `denied` 事件，`error_code="tool_unavailable"`，抛 `ToolDenied`。
- 策略拒绝：写 `denied` 事件，`error_code="policy_denied"`，抛 `ToolDenied`。
- 需要审批：写 `denied` 事件，`error_code="approval_required"`，抛 `ToolDenied`。
- 函数异常：写 `error` 事件，`error_code` 是异常类名，重新抛出。
- 成功：写 `ok` 事件，`target=tool_id`，`args_hash` 是 args JSON 的 SHA-256，`result_hash` 是输出的 SHA-256，`data_classes` 来自 `ToolSpec`，`egress="none"`。
- 审计 sink 为 None 时跳过审计，不改变调用行为。

## 5 问威胁建模（10 分钟）

1. **数据**：工具参数、工具返回值、数据分级、run 身份。
2. **调用方**：后续运行时、编排器、ADK 工具循环。
3. **信任边界**：工具函数返回值、agent 的 manifest grants。
4. **恶意输入最坏结果**：未授权工具读取敏感数据；需要审批的操作绕过审批；参数含敏感内容被写进日志。授权检查、审批门、只存 hash 分别处理。
5. **失败是否泄露信息**：审计只存参数和结果的 hash，不存原文；错误只含 tool_id 和异常类名。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.tools'`，工具测试收集失败
- 实现后绿: 目标测试 36 passed
- `check.py --fast` -> 119 tests，含 `[PASS] specs`
- `check.py --full` -> 119 tests，8 步全 PASS
- 详见 `docs/evidence/SLICE-019-tool-gateway.txt`
