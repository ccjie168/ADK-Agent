# SLICE-020 ADK 工具守卫接入（M2-2）

状态: gated
依据: ADR-0002 第 5、6 条

## 意图（要什么，不写怎么写）

把 SLICE-019 的工具策略接进 ADK 的真实工具循环。

- 每个 agent 的工具调用先过 `PolicyEngine`。拒绝时工具不执行。
- 允许、拒绝、异常都写 `tool.call` 审计。
- 守卫通过 ADK 的 `before_tool_callback`、`after_tool_callback`、`on_tool_error_callback` 接入。
- 控制台给每个 agent 和子 agent 装守卫。策略只放行 agent 自己声明的工具。
- 这是 M2 的出口条件之一：越权工具调用被拒并留痕。

## 新增文件

- `src/adk_agent/tools/guard.py`
- `tests/tools/test_guard.py`
- `tests/test_console_tools.py`
- `docs/evidence/SLICE-020-tool-guard.txt`

## 修改文件

- `src/adk_agent/tools/__init__.py`：导出 `ToolGuard`、`install_tool_guard`
- `src/adk_agent/audit/hashing.py`：新增 `safe_hash_json`
- `src/adk_agent/tools/gateway.py`：改用 `safe_hash_json`
- `src/adk_agent/console.py`：装守卫，按声明的工具生成 grants
- `docs/specs/ROADMAP.md`：标出 SLICE-020 完成

## 完成判据（可执行）

- [x] 允许的工具调用执行，写 `tool.call` `ok`，带参数 hash、结果 hash、延迟 -> `tests/tools/test_guard.py::test_allowed_tool_is_audited`
- [x] 拒绝的工具不执行，`before` 返回拒绝响应，写 `denied`，`error_code="policy_denied"` -> `::test_denied_tool_is_not_called`
- [x] 拒绝调用不重复写 `ok` 事件 -> `::test_denied_tool_is_not_called`
- [x] 工具异常写 `error`，`error_code` 是异常类名，异常继续抛出 -> `::test_tool_error_is_audited`
- [x] 无 invocation 上下文的工具调用抛 `ToolDenied` -> `::test_tool_call_without_invocation_is_denied`
- [x] 工具 `custom_metadata` 的 `data_classes` 进入审计 -> `::test_data_classes_from_tool_metadata`
- [x] `install_tool_guard` 覆盖子 agent，保留已有回调 -> `::test_install_guard_prepends_and_covers_subagents`
- [x] 端到端允许路径：脚本化模型触发工具，函数执行，审计有 `ok` -> `::test_agent_tool_call_is_guarded`
- [x] 端到端拒绝路径：脚本化模型触发未授权工具，函数不执行，审计有 `denied` -> `::test_agent_denied_tool_is_not_executed`
- [x] 控制台给 agent 装三个回调 -> `tests/test_console_tools.py::test_console_installs_tool_guard`
- [x] 控制台的策略只放行声明的工具 -> `tests/test_console_tools.py::test_console_grants_declared_tools`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools.guard import ToolGuard` -> 当前 `ModuleNotFoundError` -> 测试收集失败
- [x] 反例 2：没有守卫时 agent 的工具调用只产生 `agent.run`，没有 `tool.call` -> 端到端测试期望 `tool.call`
- [x] 反例 3：未授权工具仍然执行 -> 期望函数未被调用
- [x] 反例 4：工具异常没有审计 -> 期望 `error` 事件
- [x] 反例 5：子 agent 没有守卫 -> 期望子 agent 的回调已安装
- [x] 反例 6：控制台没有装守卫 -> 期望三个回调都存在

## 契约

`docs/contracts/` 不变。守卫复用 `PolicyEngine`、`AuditSink`、`AuditEvent`、`ToolGrant`。ADK 回调形状是外部接口，按 ADK 2.14 的签名接入。

### 回调语义

```python
class ToolGuard:
    def __init__(self, policy: PolicyEngine, audit: AuditSink | None = None) -> None: ...

    async def before(self, tool: BaseTool, args: dict, context: Context) -> dict | None: ...
    async def after(self, tool: BaseTool, args: dict, context: Context, response: Any) -> None: ...
    async def on_error(self, tool: BaseTool, args: dict, context: Context, error: Exception) -> None: ...
```

- `before`：没有 invocation 上下文时抛 `ToolDenied`。策略拒绝时写 `denied` 审计并返回 `{"error": "tool_denied", "reason": ..., "tool": ...}`。ADK 跳过工具执行。策略放行时返回 `None`。
- `after`：被 `before` 拒绝的调用不再写 `ok`。其他调用写 `ok` 审计，`result_hash` 是结果的稳定 hash。结果为空时 `result_hash=None`。
- `on_error`：写 `error` 审计，`error_code` 是异常类名。返回 `None`，由 ADK 继续抛出。
- 审计的 `action="tool.call"`、`target=tool.name`、`args_hash` 是参数的稳定 hash、`data_classes` 来自 `tool.custom_metadata["data_classes"]`、`egress="none"`。
- 审计不存参数和结果原文。
- `install_tool_guard(agent, guard)` 把守卫放在回调链最前，递归覆盖 `sub_agents`。已有回调保留并排在守卫之后。

### 控制台策略

`build_console_app` 为每个顶层 agent 建一个 `ToolGuard`。

- grants 来自 agent 树里声明的工具名。`BaseTool` 用 `.name`，普通 callable 用 `__name__`。
- 未声明的工具被拒绝。工具集（`BaseToolset`）的工具名在运行时才知道，本切片不放行，留给 SLICE-021。
- `ToolGuard` 和策略都在 `adk_agent.tools` 适配器内，`core` 不新增依赖。

## 5 问威胁建模（10 分钟）

1. **数据**：工具名、模型生成的参数、工具返回值、工具元数据里的数据分级、run 身份。
2. **调用方**：ADK 工具循环、控制台、后续编排器。
3. **信任边界**：模型生成的工具名和参数、工具自定义元数据、`PolicyEngine` 的 grants。
4. **恶意输入最坏结果**：模型调用未授权工具读取数据；守卫只装在父 agent，子 agent 绕过；参数里的敏感内容被写进日志。策略检查、递归装守卫、只存 hash 分别处理。
5. **失败是否泄露信息**：审计只存参数和结果的 hash。拒绝原因来自策略，不含密钥。错误只记录异常类名。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.tools.guard'`，两个测试模块收集失败
- 实现后绿: 目标测试 10 passed
- `check.py --fast` -> 129 tests，7 步全 PASS
- `check.py --full` -> 129 tests，9 步全 PASS
- 详见 `docs/evidence/SLICE-020-tool-guard.txt`
