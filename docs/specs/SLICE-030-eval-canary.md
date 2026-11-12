# SLICE-030 评测门禁与灰度（M4-3）

状态: gated
依据: ADR-0002 第 4、6 条

## 意图（要什么，不写怎么写）

补齐 M4 出口的第三条。

- 评测套件是数据：套件标识、版本、目标 agent、用例、匹配方式。
- 评测报告是数据：套件标识、版本、通过数、总数、逐用例结果。
- 用例判定只做确定性的 `exact` / `contains`，不引入模型裁判。
- manifest 声明了 `eval_suite` 时，发布必须带匹配且达标的报告。否则拒绝。
- 报告套件标识或版本不匹配，拒绝发布。
- 通过率低于 manifest 阈值，拒绝发布。
- CLI 提供 `eval` 命令跑套件并输出报告 JSON。
- 灰度是数据：稳定版本、候选版本、权重、租户。
- 灰度路由器按权重选版本，随机源可注入，便于测试。
- 这一刀不接真实流量分流。注册表还没有按版本的解析器。

## 新增文件

- `src/adk_agent/core/eval.py`
- `src/adk_agent/core/canary.py`
- `src/adk_agent/eval.py`
- `src/adk_agent/canary.py`
- `tests/test_eval.py`
- `tests/test_eval_gate.py`
- `tests/test_canary.py`
- `docs/contracts/eval_suite_spec.schema.json`
- `docs/contracts/eval_report.schema.json`
- `docs/contracts/canary_policy.schema.json`
- `docs/evidence/SLICE-030-eval-canary.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`：导出评测与灰度类型
- `src/adk_agent/cli.py`：`eval` 命令、`publish --eval-report`
- `scripts/export_contracts.py`：导出三个新 schema
- `docs/contracts/cli.md`：新增命令和参数
- `docs/specs/ROADMAP.md`：M4 进度

## 完成判据（可执行）

- [x] 用例命中则通过 -> `tests/test_eval.py::test_runner_passes_matching_cases`
- [x] exact 与 contains 判定不同 -> `tests/test_eval.py::test_runner_distinguishes_match_modes`
- [x] 用例异常记为失败 -> `tests/test_eval.py::test_runner_marks_errors`
- [x] 报告校验通过数不超过总数 -> `tests/test_eval.py::test_report_rejects_impossible_counts`
- [x] 门禁放行达标报告 -> `tests/test_eval.py::test_gate_allows_passing_report`
- [x] 缺报告拒绝发布 -> `tests/test_eval_gate.py::test_publish_requires_report`
- [x] 报告套件不匹配拒绝 -> `tests/test_eval.py::test_gate_rejects_suite_mismatch`
- [x] 报告不达标拒绝 -> `tests/test_eval_gate.py::test_publish_rejects_failing_report`
- [x] 达标报告可发布 -> `tests/test_eval_gate.py::test_publish_accepts_passing_report`
- [x] 没声明套件的 manifest 不受门禁 -> `tests/test_eval_gate.py::test_publish_without_suite_is_ungated`
- [x] 权重 0 全走稳定版本 -> `tests/test_canary.py::test_zero_weight_is_stable`
- [x] 权重 1 全走候选版本 -> `tests/test_canary.py::test_full_weight_is_canary`
- [x] 权重在边界按随机源决定 -> `tests/test_canary.py::test_weight_boundary_uses_random_source`
- [x] 同版本不允许正权重 -> `tests/test_canary.py::test_same_version_with_weight_rejected`
- [x] 租户不匹配拒绝路由 -> `tests/test_canary.py::test_tenant_mismatch_rejected`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.eval import EvalRunner` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.canary import CanaryRouter` -> 当前 `ImportError`
- [x] 反例 3：manifest 要求评测但 `publish` 不带报告 -> 当前发布成功，期望退出 1
- [x] 反例 4：低于阈值的报告仍然发布 -> 期望退出 1 且注册表为空
- [x] 反例 5：套件不匹配的报告放行 -> 期望 `EvalGateFailed`

## 契约

```python
class EvalCase(BaseModel):
    id: str
    input: str
    expected: str
    match: Literal["exact", "contains"] = "contains"

class EvalSuiteSpec(BaseModel):
    suite_id: str
    version: str
    agent: str
    cases: list[EvalCase]   # 至少 1 条

class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    actual: str
    error: str | None = None

class EvalReport(BaseModel):
    suite_id: str
    version: str
    passed: int
    total: int
    results: list[EvalCaseResult] = []
    # passed <= total

class CanaryPolicy(BaseModel):
    tenant: str
    agent_id: str
    stable_version: str
    canary_version: str
    weight: float   # 0 到 1
```

- `EvalRunner(call).run(suite, invocation)` 用父 invocation 派生子调用，只换输入。
- 判定：`exact` 比较去空白后的整串，`contains` 判断期望串是否在输出中。
- 实际调用抛异常时该用例记为失败，`error` 记异常类名。
- `EvalReport.score = passed / total`。
- `enforce_eval_gate(manifest, report)`：manifest 没声明套件时直接放行；声明了则要求报告存在、suite_id 和 version 一致、`score >= pass_threshold`。
- 门禁失败抛 `EvalGateFailed`。CLI `publish` 转成 stderr 和退出 1。
- CLI `eval <suite> --agents FILE [--out FILE]` 跑套件。没给 `--out` 时写 stdout。
- `CanaryRouter(rand).route(policy, tenant)`：权重 0 返回稳定版本，权重 1 返回候选版本，其余 `rand() < weight` 决定。
- 政策租户和调用租户不一致时抛 `ValueError`。
- 正权重且两个版本相同，策略非法。

## 5 问威胁建模（10 分钟）

1. **数据**：用例输入与期望输出、评测结果、套件阈值、灰度权重、版本。
2. **调用方**：CI、发布 CLI、后续网关。
3. **信任边界**：套件文件、报告文件、注册表、随机源。
4. **恶意输入最坏结果**：伪造达标报告发布坏版本；报告套件号对不上仍放行；灰度权重配错把全部流量打到候选；用例输出泄漏敏感数据。用门禁强校验、套件号比对、权重范围和版本约束、报告只存实际输出不做额外持久化处理。
5. **失败是否泄露信息**：CLI 失败只输出原因类别和分数。报告里含实际输出，属于评测产物，按调用方权限处理。

### 已知边界

- 判定只有确定性匹配，没有语义或模型裁判。
- 报告可由人伪造。门禁信任报告文件。要防伪需要签名报告，排在后续。
- 灰度路由器还没接流量。注册表没有按版本解析的入口，接入排在后续切片。
- 评测 CLI 用内存会话，每次用例新建会话。
- 审计没有 `eval.run` 事件。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.canary'`，2 个测试模块收集失败
- 实现后绿: 评测、门禁、灰度测试 20 passed
- 真实 CLI: 脚本化 agent 跑 2 个用例全过；达标报告发布成功；不达标和缺报告都退出 1 且没写注册表
- `check.py --fast` -> 292 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 292 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-030-eval-canary.txt`
