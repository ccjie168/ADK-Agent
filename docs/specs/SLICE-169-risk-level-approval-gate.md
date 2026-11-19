# SLICE-169 审批门按 risk_level 驱动 + 审计字段

状态: gated
依据: ADR-0029（Accepted 2026-11-19）决定 3：审批要求由风险等级推导；slice 3 让 `PlanExecutor`
审批门按 risk_level 驱动，并把 risk_level 写进审计事件。

## 意图

1. `PlanStep` 增加计算属性 `needs_approval`：`requires_approval or risk_level in ("L3", "L4")`。
2. `PlanExecutor` 的两处审批判断（`_run_sequential` 检查点、`_run_step` 审批门）改用
   `step.needs_approval`。
3. `AuditEvent` 增加可选 `risk_level: RiskLevel | None = None`；`_audit_step` 写入 `step.risk_level`。
4. 重生成 `audit_event.schema.json`。

## 契约（先改）

- `docs/contracts/audit_event.schema.json` 重生成（新增可选 risk_level）。

## 完成判据

- [x] L3 风险步骤即使 `requires_approval=False` 也需审批 -> `test_step_needs_approval_for_l3_risk`
- [x] L2 风险步骤且无审批标志不需审批 -> `test_step_no_approval_for_l2_risk`
- [x] 审批标志本身仍生效 -> `test_step_approval_flag_still_wins`
- [x] 审计事件携带 risk_level -> `test_audit_event_carries_risk_level`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `PlanStep` 无 `needs_approval` 属性，`risk_level="L3"` 不触发审批

## 5 问威胁建模

1. **数据**：计划步骤的风险分级与审批要求。
2. **调用方**：计划编排者、PlanExecutor。
3. **信任边界**：计划 schema 到执行器审批门。
4. **恶意输入最坏结果**：L3/L4 步骤绕过审批（缓解：needs_approval 从 risk_level 推导，不依赖布尔）。
5. **失败是否泄露信息**：无新增错误面。

## 范围外

- L4 默认拒绝（ADR-0029 slice 4）。
- ADR-0034 写工具幂等。

## 证据

- `docs/evidence/SLICE-169-risk-level-approval-gate.txt`
