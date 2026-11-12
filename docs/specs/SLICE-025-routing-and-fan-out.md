# SLICE-025 路由与扇出扇入（M3-3）

状态: gated
依据: ADR-0002 第 4 条

## 意图（要什么，不写怎么写）

给计划增加两种确定性策略。

- 路由：按父输入匹配规则，选一个步骤执行。规则是计划数据，不写进 prompt。
- 扇出扇入：无依赖的步骤并发执行，汇合步骤等所有分支完成并拼接输出。
- 两种策略都经过已有的策略检查、重试、超时、预算、取消和审计。
- 这一刀不做监督者、审批和 trace 树。

## 新增文件

- `tests/orchestration/test_strategies.py`
- `docs/evidence/SLICE-025-routing-and-fan-out.txt`

## 修改文件

- `src/adk_agent/core/orchestration.py`：`RouteWhen`、`route_when`、`max_parallel`、`routing` / `fan_out` 策略和校验
- `src/adk_agent/core/__init__.py`：导出 `RouteWhen`
- `src/adk_agent/orchestration/errors.py`：`NoRoute`
- `src/adk_agent/orchestration/executor.py`：路由和扇出调度
- `src/adk_agent/orchestration/__init__.py`：导出 `NoRoute`
- `src/adk_agent/__init__.py`：导出 `RouteWhen`、`NoRoute`
- `docs/contracts/orchestration_plan.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：M3 切片状态

## 完成判据（可执行）

- [x] 路由命中第一个匹配步骤 -> `tests/orchestration/test_strategies.py::test_routing_selects_matching_step`
- [x] 路由使用默认步骤 -> `::test_routing_uses_default`
- [x] 无匹配且无默认时抛 `NoRoute`，不调用 agent -> `::test_routing_no_match_fails`
- [x] 路由形状校验 -> `::test_routing_validation`
- [x] 三种匹配算子 -> `::test_route_when_operators`
- [x] 扇出分支并发执行，汇合步骤拼接输出 -> `::test_fan_out_runs_branches_concurrently`
- [x] 扇出必须只有一个汇合点 -> `::test_fan_out_requires_one_sink`
- [x] 扇出批次超预算时计划被拒，汇合步骤不执行 -> `::test_fan_out_budget_post_check`
- [x] 契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import RouteWhen` -> 当前 `ImportError`
- [x] 反例 2：两个默认路由步骤被接受 -> 期望 `ValidationError`
- [x] 反例 3：扇出两个汇合点被接受 -> 期望 `ValidationError`
- [x] 反例 4：扇出分支实际串行执行 -> 并发测试会超时
- [x] 反例 5：无匹配路由仍然调用默认之外的第一步 -> 期望 `NoRoute`

## 契约

```python
PlanStrategy = Literal["single", "sequential", "routing", "fan_out"]

class RouteWhen(BaseModel):
    equals: str | None = None
    contains: str | None = None
    prefix: str | None = None
    # 恰好一个算子
    def matches(self, text: str) -> bool: ...

class PlanStep(BaseModel):
    ...
    route_when: RouteWhen | None = None

class OrchestrationPlan(BaseModel):
    ...
    max_parallel: int = 1   # 1..16
```

- `route_when` 只允许 `routing`。路由步骤不能有依赖或输入引用。
- 路由最多一个默认步骤，且必须在最后。匹配按声明顺序，先命中先执行。
- 没有默认且没有命中时抛 `NoRoute`，写 `orchestration.run` `error` `no_route`。
- `fan_out` 必须有唯一汇合点，即没有其他步骤依赖它的步骤。
- `fan_out` 的 `max_parallel` 控制批次大小。默认 1，等于串行。
- 扇出批次内的步骤共享批次开始时的剩余预算。批次结束后汇总成本并检查父预算。
- 扇出的最终文本是汇合点的输出。
- 路由的最终文本是选中步骤的输出。

## 5 问威胁建模（10 分钟）

1. **数据**：父输入、路由规则、分支输出、汇合输出、预算。
2. **调用方**：控制台、CLI、后续编排器。
3. **信任边界**：计划数据、路由规则、并发分支。
4. **恶意输入最坏结果**：路由规则选中错误分支；扇出无限并发；汇合点缺失；预算被并发分支绕过。用确定性规则、`max_parallel` 上限、形状校验、批次后预算检查处理。
5. **失败是否泄露信息**：审计只存 hash。路由事件只记录选中的 step id。错误只记录类名和步骤 id。

## 证据

- 反例红: `ImportError: cannot import name 'RouteWhen'`，测试收集失败
- 实现后绿: 策略测试 8 passed，编排套件 40 passed
- `check.py --fast` -> 223 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 223 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-025-routing-and-fan-out.txt`
