# SLICE-026 监督者策略（M3-4）

状态: gated
依据: ADR-0002 第 4、5、6 条

## 意图（要什么，不写怎么写）

让一个监督 agent 在有限轮次内选择 worker。

- 计划声明 supervisor、可用 worker 和最大轮次。
- 每轮把任务、worker 列表和已执行历史交给 supervisor。
- supervisor 只返回结构化 JSON：调用某个 worker，或结束。
- 执行器校验 worker 名、JSON 结构和轮次上限。非法决策不执行。
- 每次 supervisor 决策、worker 调用都写审计。
- 复用已有的策略检查、超时、预算、取消和审计。
- 这一刀不做审批和 trace 树。

## 新增文件

- `docs/contracts/supervisor_decision.schema.json`
- `tests/orchestration/test_supervisor.py`
- `docs/evidence/SLICE-026-supervisor.txt`

## 修改文件

- `src/adk_agent/core/orchestration.py`：`SupervisorDecision`、`supervisor`、`max_rounds`、`supervisor` 策略和校验
- `src/adk_agent/core/__init__.py`：导出 `SupervisorDecision`
- `src/adk_agent/orchestration/errors.py`：`SupervisorProtocolError`、`SupervisorLimit`
- `src/adk_agent/orchestration/executor.py`：监督者循环、状态拼接、决策解析、审计
- `src/adk_agent/orchestration/__init__.py`：导出新错误
- `src/adk_agent/__init__.py`：导出新类型
- `scripts/export_contracts.py`：新增 `supervisor_decision.schema.json`
- `docs/contracts/orchestration_plan.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：M3 切片状态

## 完成判据（可执行）

- [x] supervisor 调用 worker 后结束 -> `tests/orchestration/test_supervisor.py::test_supervisor_calls_worker_then_done`
- [x] supervisor 立即结束，不调用 worker -> `::test_supervisor_done_immediately`
- [x] done 的 final 为空时用最后一次输出 -> `::test_supervisor_done_empty_final_uses_last_output`
- [x] 未知 worker 不执行，写 `supervisor_protocol` -> `::test_supervisor_unknown_worker`
- [x] 非 JSON 决策不执行，写 `supervisor_protocol` -> `::test_supervisor_invalid_json`
- [x] 轮次用尽写 `round_limit` -> `::test_supervisor_round_limit`
- [x] supervisor 被策略拒绝时不调用 -> `::test_supervisor_policy_denied`
- [x] 超预算计划被拒 -> `::test_supervisor_budget`
- [x] 计划形状和决策形状校验 -> `::test_supervisor_validation`
- [x] 契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import SupervisorDecision` -> 当前 `ImportError`
- [x] 反例 2：supervisor 缺失仍然执行 -> 期望 `ValidationError`
- [x] 反例 3：未知 worker 仍然被调用 -> 期望 `SupervisorProtocolError`
- [x] 反例 4：非 JSON 仍然被当作决策 -> 期望 `SupervisorProtocolError`
- [x] 反例 5：无限轮次 -> 期望 `SupervisorLimit`

## 契约

```python
PlanStrategy = Literal["single", "sequential", "routing", "fan_out", "supervisor"]

class SupervisorDecision(BaseModel):
    action: Literal["call", "done"]
    worker: str | None = None   # action=call 时必填
    input: str = ""             # 为空时用父输入
    final: str = ""             # action=done 时使用

class OrchestrationPlan(BaseModel):
    ...
    supervisor: AgentRef | None = None
    max_rounds: int = 5          # 1..20
```

- `supervisor` 只允许 `supervisor` 策略。worker 步骤不能有依赖、输入引用或路由条件。
- supervisor id 不能和 worker 的 step id 或 agent id 相同。
- 每轮 supervisor 输入包含任务、轮次、worker 列表、回复格式和已执行历史。
- supervisor 输出必须是纯 JSON。解析失败写 `supervisor_protocol`。
- `worker` 必须是计划的 step id。未知 worker 写 `supervisor_protocol`。
- `action="done"` 时结束。`final` 为空时用最后一次 worker 输出。
- `max_rounds` 是 supervisor 决策次数上限。用尽仍要 call 时写 `round_limit`。
- supervisor 调用经过 `agent.invoke` 策略检查。worker 调用经过已有检查。
- worker 输出按 `step_id#round` 存入 `PlanResult.outputs`。
- 审计动作：`orchestration.supervisor`（target=`round:<n>`）、`orchestration.step`、`orchestration.run`。
- supervisor 成本计入 `PlanResult.cost_usd`。

## 5 问威胁建模（10 分钟）

1. **数据**：任务输入、worker 历史、supervisor 决策、worker 输出、成本。
2. **调用方**：控制台、CLI、后续编排器。
3. **信任边界**：supervisor 模型输出、worker 输出、计划定义。
4. **恶意输入最坏结果**：supervisor 选择未授权 worker；决策不是 JSON 被当作命令；worker 输出注入指令影响 supervisor；无限轮次烧预算。用 worker 名校验、JSON 解析、决策空间受限、轮次上限和已有预算检查处理。
5. **失败是否泄露信息**：审计只存输入输出的 hash。supervisor 事件只记录轮次和状态。错误只记录类名和 worker id。

### 提示注入说明

worker 输出会原样进入 supervisor 的历史。恶意 worker 可能诱导 supervisor 做出错误选择。限制是决策只能落在计划的 worker 集合内，最终动作和执行都由执行器校验并审计。审批门在 SLICE-027 补。

## 证据

- 反例红: `ImportError: cannot import name 'SupervisorDecision'`，测试收集失败
- 实现后绿: 监督者测试 9 passed，编排套件 49 passed
- `check.py --fast` -> 232 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 232 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-026-supervisor.txt`
