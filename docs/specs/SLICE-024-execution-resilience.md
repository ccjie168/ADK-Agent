# SLICE-024 执行韧性（M3-2）

状态: gated
依据: ADR-0002 第 4、6 条

## 意图（要什么，不写怎么写）

让计划执行在失败和资源边界下可预期。

- 每个步骤可以重试。重试次数和间隔是计划数据。
- 每个步骤有超时。超时取消调用，写 `StepTimeout`。
- 父 deadline 限制整个计划。超时写 `plan_timeout`。
- 父预算和步骤预算在调用前检查，调用后扣减。超支写 `budget_exceeded`。
- 调用方可以取消计划。取消在步骤之间、调用中和重试等待中都生效。
- 每次重试写 `orchestration.retry`。最终结果写 `orchestration.step` 和 `orchestration.run`。
- 这一刀不做审批、trace 树、路由、监督者、扇出扇入。

## 新增文件

- `src/adk_agent/orchestration/cancel.py`
- `tests/orchestration/test_resilience.py`
- `docs/evidence/SLICE-024-execution-resilience.txt`

## 修改文件

- `src/adk_agent/core/invocation.py`：`InvocationResult.cost_usd`
- `src/adk_agent/core/orchestration.py`：`PlanStep.max_attempts`、`retry_backoff_seconds`、`PlanResult.cost_usd`
- `src/adk_agent/orchestration/errors.py`：`PlanCancelled`、`PlanTimeout`、`StepTimeout`、`BudgetExceeded`
- `src/adk_agent/orchestration/executor.py`：重试、超时、预算、取消
- `src/adk_agent/orchestration/__init__.py`：导出新类型
- `src/adk_agent/__init__.py`：导出新类型
- `docs/contracts/orchestration_plan.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：M3 切片状态

## 完成判据（可执行）

- [x] 失败后重试成功 -> `tests/orchestration/test_resilience.py::test_retry_until_success`
- [x] 重试耗尽抛 `PlanExecutionError`，写 retry 和 error 审计 -> `::test_retry_exhausted`
- [x] 步骤超时后重试成功 -> `::test_timeout_is_retried_then_succeeds`
- [x] 步骤超时耗尽抛 `StepTimeout` -> `::test_step_timeout_exhausted`
- [x] 父 deadline 过期时不调用 agent -> `::test_plan_deadline_expired`
- [x] 父 deadline 限制步骤超时，且不重试 -> `::test_plan_deadline_limits_step_and_does_not_retry`
- [x] 步骤花费超过父预算后计划被拒 -> `::test_budget_exceeded_after_step`
- [x] 预算用尽后下一步不执行 -> `::test_budget_blocks_next_step`
- [x] 步骤花费超过步骤预算 -> `::test_step_budget_exceeded`
- [x] 运行前取消 -> `::test_cancellation_before_run`
- [x] 调用中取消 -> `::test_cancellation_during_step`
- [x] 计划结果累计成本 -> `::test_result_cost_is_summed`
- [x] 契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.orchestration import BudgetExceeded` -> 当前 `ImportError`
- [x] 反例 2：步骤失败仍然只调用一次 -> 期望按 `max_attempts` 重试
- [x] 反例 3：慢步骤不超时 -> 期望 `StepTimeout`
- [x] 反例 4：超预算仍然执行下一步 -> 期望 `BudgetExceeded`
- [x] 反例 5：取消后仍然调用 agent -> 期望 `PlanCancelled`

## 契约

```python
class PlanStep(BaseModel):
    ...
    max_attempts: int = 1          # 1..5
    retry_backoff_seconds: float = 0.0  # 0..60

class InvocationResult(BaseModel):
    ...
    cost_usd: float = 0.0

class PlanResult(BaseModel):
    ...
    cost_usd: float = 0.0

class CancellationToken:
    def cancel(self) -> None: ...
    @property
    def cancelled(self) -> bool: ...
    async def wait(self) -> None: ...

class PlanExecutor:
    async def run(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None = None,
    ) -> PlanResult: ...
```

- 重试：只重试 agent 调用失败和步骤超时。策略拒绝、未知 agent、取消不重试。
- 重试间隔 `retry_backoff_seconds`。等待期间可取消。
- 超时：每次尝试单独计时。有效超时是 `timeout_seconds` 和父 deadline 剩余时间的较小值。
- 父 deadline 导致的超时抛 `PlanTimeout`，不重试。
- 预算：调用前检查剩余预算。剩余为 0 时拒绝。调用后累计 `cost_usd`。
- 步骤花费超过步骤预算时，步骤写 `error` `budget_exceeded`，计划写 `denied`。
- 父预算在最后一步超支时，步骤写 `ok`，计划写 `denied` `budget_exceeded`。
- 取消：步骤之间检查 token。调用中使用 `asyncio.wait` 同时等待调用和 token。取消时取消调用任务。
- 重试事件 `action="orchestration.retry"`，`target="<step>#<attempt>"`，`status="error"`。
- `orchestration.step` 只在最终结果写一次。重试事件单独写。
- 成本来自 `InvocationResult.cost_usd`。默认 0.0。runtime 适配器要填这个字段，预算才是真的。

## 5 问威胁建模（10 分钟）

1. **数据**：步骤输入输出、重试次数、超时、预算、成本、取消信号。
2. **调用方**：控制台、CLI、后续编排器。
3. **信任边界**：计划数据、agent 返回的成本、调用方取消。
4. **恶意输入最坏结果**：重试风暴；预算被绕过；超时任务继续跑；取消后仍然输出。分别用上限、调用前后预算检查、任务取消、token 检查处理。
5. **失败是否泄露信息**：审计只存 hash。错误只记录类名、步骤 id 和重试次数。成本只记数字。

## 证据

- 反例红: `ImportError: cannot import name 'BudgetExceeded'`，测试收集失败
- 实现后绿: 韧性测试 12 passed，编排套件 32 passed
- `check.py --fast` -> 215 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 215 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-024-execution-resilience.txt`
