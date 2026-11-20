# SLICE-187 模型预算执行

状态: gated
依据: ADR-0033（Accepted 2026-11-19）决定 4 / slice 3：每租户预算；超限停止（MVP 先停止，不降级）。
`ModelPolicy.budget_usd` 目前声明未执行，本切片落地执行。

## 意图

1. `models/budget.py` 新增 `BudgetTracker`：按租户累计 USD（`spent`/`add`），进程内。
2. `PolicyModelGateway` 增加可选 `budgets`；`_complete_once` 在调用 provider 前检查：
   `policy.budget_usd` 非空且该租户已花费达到上限时，审计 `budget_exceeded` 并抛 `ModelDenied`。
3. 调用成功后把 `response.cost_usd` 累加到该租户。
4. 未配置 `budgets` 时不执行预算，行为与现状一致。

## 契约（先改）

- 无对外 schema 变更（预算为网关内部执行）。

## 完成判据

- [ ] 未超预算放行并累计花费 -> `test_budget_allows_and_accumulates`
- [ ] 达到上限拒绝 -> `test_budget_denies_at_limit`
- [ ] 拒绝时不调用 provider -> `test_budget_denial_skips_provider`
- [ ] 无 tracker 不执行预算 -> `test_no_tracker_no_enforcement`
- [ ] 不同租户预算互不影响 -> `test_budget_is_per_tenant`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `budget_usd` 不生效：超限后仍调用 provider（`BudgetTracker` 不存在）

## 5 问威胁建模

1. **数据**：每租户模型花费累计与预算上限。
2. **调用方**：模型网关（进程内、独立服务）。
3. **信任边界**：策略声明到执行。
4. **恶意输入最坏结果**：预算不执行导致成本失控（缓解：调用前检查 + 成功后累计，fail-closed 拒绝）。
5. **失败是否泄露信息**：仅 `ModelDenied`，审计记 `budget_exceeded`，不泄露其他租户花费。

## 范围外

- 预算持久化与跨副本共享（后续，需存储选型）。
- 超限降级到备用候选（ADR-0033 定为后置；MVP 先停止）。
- 审计字段扩展（slice 4）。

## 证据

- `docs/evidence/SLICE-187-model-budget.txt`
