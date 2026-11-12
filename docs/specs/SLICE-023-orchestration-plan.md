# SLICE-023 编排计划与执行器（M3-1）

状态: gated
依据: ADR-0002 第 4、5、6 条

## 意图（要什么，不写怎么写）

把编排计划变成数据。

- `OrchestrationPlan` 描述单 agent 或顺序多 agent 工作流。
- 计划有稳定 digest。执行器把 digest 写进审计。
- `PlanExecutor` 按拓扑序执行步骤，不把编排逻辑写进 prompt。
- 每个步骤经过 `PolicyEngine` 的 `agent.invoke` 检查。拒绝的步骤不执行。
- 每个步骤是独立的一次 `Invocation`，沿用父 trace_id，步骤间通过步骤输出拼输入。
- 审计覆盖 `orchestration.run` 和 `orchestration.step`。
- 这一刀不做重试、预算强制、超时强制、取消、审批和 trace 树。它们排在后续 M3 切片。

## 新增文件

- `src/adk_agent/core/orchestration.py`
- `src/adk_agent/orchestration/__init__.py`
- `src/adk_agent/orchestration/errors.py`
- `src/adk_agent/orchestration/policy.py`
- `src/adk_agent/orchestration/executor.py`
- `tests/orchestration/test_plan.py`
- `tests/orchestration/test_orchestration_policy.py`
- `tests/orchestration/test_executor.py`
- `docs/contracts/orchestration_plan.schema.json`
- `docs/evidence/SLICE-023-orchestration-plan.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`：导出计划类型
- `src/adk_agent/__init__.py`：导出计划和执行器
- `scripts/export_contracts.py`：新增 `orchestration_plan.schema.json`
- `.importlinter`：`core` 禁止导入 `adk_agent.orchestration`
- `docs/specs/ROADMAP.md`：M3 切片状态

## 完成判据（可执行）

- [x] 单 agent 计划可 JSON 往返，digest 稳定 -> `tests/orchestration/test_plan.py::test_plan_roundtrip_and_digest`
- [x] 重复 step id 被拒绝 -> `::test_duplicate_step_ids_rejected`
- [x] 未知依赖被拒绝 -> `::test_unknown_dependency_rejected`
- [x] 依赖环被拒绝 -> `::test_cycle_rejected`
- [x] `inputs_from` 必须出现在 `depends_on` -> `::test_inputs_from_must_be_dependency`
- [x] single 策略只能有一个步骤 -> `::test_single_strategy_shape`
- [x] 拓扑序稳定 -> `::test_order_is_stable`
- [x] 单步骤计划执行一次，使用父输入 -> `tests/orchestration/test_executor.py::test_single_plan_uses_parent_input`
- [x] 顺序计划按拓扑序执行，步骤输入拼接上游输出 -> `::test_sequential_plan_composes_inputs`
- [x] 拒绝的 agent 不执行，写 `denied` 步骤审计 -> `::test_denied_agent_is_not_called`
- [x] 未注册 agent 失败，写 `unknown_agent` -> `::test_unknown_agent_fails`
- [x] 步骤异常被包装，写原错误类名 -> `::test_step_error_is_audited`
- [x] 计划和步骤审计共享 trace_id -> `::test_audit_shares_trace_id`
- [x] 子调用使用步骤 agent_ref、新 run_id、父 trace_id -> `::test_child_invocation_shape`
- [x] 计划级审计带计划 digest -> `::test_plan_audit_has_digest`
- [x] `AgentGrantPolicyEngine` 只放行授权 agent -> `tests/orchestration/test_orchestration_policy.py`
- [x] 契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.orchestration import PlanExecutor` -> 当前 `ModuleNotFoundError`
- [x] 反例 2：依赖环计划被接受 -> 期望 `ValidationError`
- [x] 反例 3：未授权 agent 仍然被调用 -> 期望 `PlanDenied` 且调用次数为 0
- [x] 反例 4：步骤异常没有计划级审计 -> 期望 `orchestration.run` error
- [x] 反例 5：计划 digest 不进审计 -> 期望计划事件 `agent_ref.digest == plan_digest`

## 契约

```python
class PlanStep(BaseModel):
    id: str
    agent_ref: AgentRef
    input: str = ""
    inputs_from: list[str] = []
    depends_on: list[str] = []
    timeout_seconds: float | None = None
    budget_usd: float | None = None

class OrchestrationPlan(BaseModel):
    plan_id: str
    version: str
    strategy: Literal["single", "sequential"] = "single"
    steps: list[PlanStep] = Field(min_length=1)

class PlanResult(BaseModel):
    plan_id: str
    version: str
    run_id: str
    trace_id: str
    outputs: dict[str, str] = {}
    final_text: str = ""
```

- 步骤 id 和 plan_id 用安全名模式。
- `depends_on` 决定顺序。`inputs_from` 决定输入拼接，并且必须是 `depends_on` 的子集。
- 没有环。`order()` 返回稳定拓扑序，同层按声明顺序。
- `strategy="single"` 时只能有一个步骤，不能有依赖或输入引用。
- `plan_digest` 是规范 JSON 的 SHA-256。
- 步骤输入：`input` 非空则先用它，再接 `inputs_from` 的输出。都为空时用父 invocation 的输入。
- 子 invocation：新 `run_id`，父 `trace_id`，父 principal，步骤 `agent_ref`。deadline 取父 deadline 和 `now + timeout_seconds` 的较早值。预算取两者较小值。
- `PolicyEngine.decide(parent, "agent.invoke", step.agent_ref.id)` 拒绝时写 `orchestration.step` `denied`，抛 `PlanDenied`。
- agent 映射按 id 取。未注册抛 `UnknownAgent`。
- 步骤异常写 `orchestration.step` `error`，再抛 `PlanExecutionError`，保留原错误类名。
- 计划级审计 `action="orchestration.run"`，`agent_ref` 是 `plan_ref(plan)`，带计划 digest。

## 5 问威胁建模（10 分钟）

1. **数据**：计划定义、步骤输入、步骤输出、agent ref、digest、trace_id。
2. **调用方**：控制台、CLI、后续编排器。
3. **信任边界**：计划 JSON、agent 映射、策略引擎、被调 agent。
4. **恶意输入最坏结果**：计划调用未授权 agent；计划把敏感输出传给不该看的步骤；计划形成环或耗尽资源。策略检查、显式输入引用、校验和拓扑序分别处理。
5. **失败是否泄露信息**：审计只存输入输出的 hash。计划事件记录 digest，不存计划原文。步骤错误只记录类名和步骤 id。

## 证据

- 反例红: `ImportError: cannot import name 'OrchestrationPlan'`，3 个测试模块收集失败
- 实现后绿: 目标测试 20 passed
- `check.py --fast` -> 203 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 203 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-023-orchestration-plan.txt`
