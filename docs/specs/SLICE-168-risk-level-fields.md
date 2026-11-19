# SLICE-168 risk_level 字段扩展到 ToolEntry/PlanStep/ConnectorSpec

状态: gated
依据: ADR-0029（Accepted 2026-11-19）决定 1：risk_level 落在 `ToolEntry`、`ToolGrant`、`PlanStep`
与连接器派生字段。本刀把 `risk_level` 加到 `ToolEntry`、`PlanStep`、`ConnectorSpec`，并重生成契约。

## 意图

1. `ToolEntry`（`tools/catalog.py`）、`PlanStep`（`core/orchestration.py`）、`ConnectorSpec`
   （`core/connectors.py`）各增加 `risk_level: RiskLevel | None = None`（可选，向后兼容）。
2. 重生成受影响契约 schema。

## 契约（先改）

- 无对外接口变化，仅新增可选字段；重生成 `docs/contracts/` 受影响 schema。

## 完成判据

- [x] `ToolEntry` 接受合法 risk_level -> `test_tool_entry_accepts_risk_level`
- [x] `PlanStep` 接受合法 risk_level -> `test_plan_step_accepts_risk_level`
- [x] `ConnectorSpec` 接受合法 risk_level -> `test_connector_spec_accepts_risk_level`
- [x] 非法 risk_level 被拒 -> `test_risk_level_fields_reject_unknown`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上三个类型无 `risk_level` 字段，`risk_level="L3"` 被 `extra="forbid"` 拒绝

## 5 问威胁建模

1. **数据**：工具目录项、计划步骤、连接器的风险分级。
2. **调用方**：manifest 发布者、计划编排者、连接器登记方。
3. **信任边界**：schema 校验边界。
4. **恶意输入最坏结果**：非法分级绕过后续审批（缓解：Literal 约束在 schema 层拒绝非法值）。
5. **失败是否泄露信息**：无新增错误面。

## 范围外

- `PlanExecutor` 审批门按 risk_level 驱动（slice 3）。
- L4 默认拒绝（slice 4）。

## 证据

- `docs/evidence/SLICE-168-risk-level-fields.txt`
