# SLICE-027 人工审批与 trace 树（M3-5）

状态: gated
依据: ADR-0002 第 4、6 条

## 意图（要什么，不写怎么写）

补齐 M3 出口。

- 计划步骤可以要求人工审批。没有审批不执行。
- 审批请求和决定是数据。决定带审批人、理由、时间。
- 审批事件写审计，带审批人和请求 id。
- 审计事件增加 `approver` 字段。
- 从审计事件构建 trace 树，支持回放。
- 监督者的 worker 步骤嵌套在对应轮次下。
- 这一刀不做审批 UI。控制台审批流排在 M4。

## 新增文件

- `src/adk_agent/core/approval.py`
- `src/adk_agent/orchestration/approval.py`
- `src/adk_agent/orchestration/trace.py`
- `tests/orchestration/test_approval.py`
- `tests/orchestration/test_trace.py`
- `docs/evidence/SLICE-027-approval-and-trace.txt`

## 修改文件

- `src/adk_agent/core/audit.py`：`approver`
- `src/adk_agent/core/ports.py`：`ApprovalGate`
- `src/adk_agent/core/orchestration.py`：`PlanStep.requires_approval`、`approval_reason`、`TraceNode`
- `src/adk_agent/core/__init__.py`：导出审批和 trace 类型
- `src/adk_agent/orchestration/errors.py`：`ApprovalRequired`、`ApprovalDenied`、`ApprovalTimeout`、`ApprovalProtocolError`
- `src/adk_agent/orchestration/executor.py`：审批门、审计成本、trace 数据
- `src/adk_agent/orchestration/__init__.py`：导出审批和 trace
- `src/adk_agent/__init__.py`：导出新类型
- `docs/contracts/audit_event.schema.json`：重新生成
- `docs/contracts/orchestration_plan.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：M3 完成

## 完成判据（可执行）

- [x] 审批通过后步骤执行 -> `tests/orchestration/test_approval.py::test_approved_step_runs`
- [x] 审批拒绝后步骤不执行 -> `::test_denied_step_does_not_run`
- [x] 没有审批门时 fail closed -> `::test_missing_gate_fails_closed`
- [x] 审批响应和请求不匹配时拒绝 -> `::test_approval_protocol_mismatch`
- [x] 审批超时 -> `::test_approval_timeout`
- [x] 审批请求带 step、trace、agent、principal、input、reason -> `::test_approved_step_runs`
- [x] 审批审计带审批人和请求 id -> `::test_approved_step_runs`
- [x] trace 有计划和步骤节点 -> `tests/orchestration/test_trace.py::test_trace_has_plan_and_steps`
- [x] trace 标记错误 -> `::test_trace_marks_errors`
- [x] 监督者轮次嵌套 worker 步骤 -> `::test_trace_nests_supervisor_rounds`
- [x] 找不到 trace 时返回错误节点 -> `::test_trace_not_found`
- [x] 契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.orchestration import ApprovalProtocolError` -> 当前 `ImportError`
- [x] 反例 2：要求审批但没有门仍然执行 -> 期望 `ApprovalRequired`
- [x] 反例 3：审批拒绝仍然执行 -> 期望 `ApprovalDenied` 且调用次数为 0
- [x] 反例 4：审批返回别人的 request_id 仍然执行 -> 期望 `ApprovalProtocolError`
- [x] 反例 5：`build_trace` 不存在 -> 当前 `ImportError`

## 契约

```python
class ApprovalRequest(BaseModel):
    request_id: str
    run_id: str
    trace_id: str
    step_id: str
    agent_ref: AgentRef
    principal: Principal
    input: str
    reason: str = ""
    requested_at: datetime

class ApprovalDecision(BaseModel):
    request_id: str
    approved: bool
    approver: str
    reason: str = ""
    decided_at: datetime

class ApprovalGate(Protocol):
    async def request(self, request: ApprovalRequest) -> ApprovalDecision: ...

class PlanStep(BaseModel):
    ...
    requires_approval: bool = False
    approval_reason: str = ""

class TraceNode(BaseModel):
    id: str
    kind: Literal["plan", "step", "supervisor", "approval"]
    status: Literal["ok", "error", "denied"]
    error_code: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    children: list[TraceNode] = []
```

- 审批在策略检查、未知 agent 检查之后，agent 调用之前。
- 没有 `ApprovalGate` 且步骤要求审批时，写 `approval_required`，不执行。
- 审批拒绝写 `orchestration.approval` `denied` 和 `orchestration.step` `denied`，不执行。
- 审批响应的 `request_id` 必须和请求一致。不一致写 `approval_protocol`。
- 审批等待受父 deadline 限制。超时写 `approval_timeout`。
- 审批等待可被 `CancellationToken` 取消。
- `orchestration.approval` 带 `approver`、`policy_decision_id=request_id`。
- `AuditEvent` 增加 `approver: str | None = None`。
- 计划级和步骤级审计写 `cost_usd`。
- `build_trace(events, trace_id)` 从审计事件构建树。
- 根节点是 `orchestration.run`，子节点是 step、supervisor、approval。
- 有 supervisor 事件时，按时间区间把 worker 和审批事件嵌套到轮次下。
- 找不到 run 事件时返回 `trace_not_found` 节点。

## 5 问威胁建模（10 分钟）

1. **数据**：待审批输入、审批人、审批理由、trace 节点、成本。
2. **调用方**：控制台、CLI、后续审批 UI。
3. **信任边界**：审批门实现、审批人身份、审计事件。
4. **恶意输入最坏结果**：没有审批就执行高风险步骤；伪造审批响应；审批请求泄露敏感输入；trace 被篡改。用 fail closed、request_id 校验、审计只存 hash、追加事件流处理。
5. **失败是否泄露信息**：审计只存输入 hash 和审批人 id。错误只记录类名和步骤 id。审批请求本身含输入，只在审批边界内传递。

### 已知边界

- 审批 UI 没做。`ApprovalGate` 是接口，测试用回调门。
- 审批人身份目前是字符串，没有接 OIDC。
- trace 树从审计事件推导，依赖时间戳排序。跨进程时钟偏差可能影响嵌套。
- 审计哈希链和篡改检测排在 M4。
- 成本仍依赖 `InvocationResult.cost_usd`。当前 `AgentRuntime` 默认 0.0。

## 证据

- 反例红: `ImportError: cannot import name 'build_trace'`，2 个测试模块收集失败
- 实现后绿: 审批和 trace 测试 9 passed，编排套件 58 passed
- `check.py --fast` -> 241 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 241 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-027-approval-and-trace.txt`
