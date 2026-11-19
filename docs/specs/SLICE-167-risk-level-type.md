# SLICE-167 风险分级类型 RiskLevel

状态: gated
依据: ADR-0029（Accepted 2026-11-19）决定 1：新增 `risk_level: Literal["L1","L2","L3","L4"]`。
本刀只加核心类型与 `ToolGrant.risk_level` 字段，行为驱动（审批门、L4 拒绝）在后续切片。

## 意图

1. `core/policy.py` 新增 `RiskLevel = Literal["L1", "L2", "L3", "L4"]`。
2. `ToolGrant` 增加 `risk_level: RiskLevel | None = None`（可选，向后兼容旧记录）。
3. 重生成契约 schema（`tool_gateway_request.schema.json`、`manifest.schema.json` 内嵌的 ToolGrant）。

## 契约（先改）

- 无对外接口变化，仅新增可选字段；重生成 `docs/contracts/` 受影响 schema。

## 完成判据

- [x] `ToolGrant` 接受合法 risk_level -> `test_tool_grant_accepts_risk_level`
- [x] `ToolGrant` 拒绝非法 risk_level -> `test_tool_grant_rejects_unknown_risk_level`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `ToolGrant` 无 `risk_level` 字段，`risk_level="L5"` 被 `extra="forbid"` 拒绝

## 5 问威胁建模

1. **数据**：工具授权的风险分级。
2. **调用方**：manifest 发布者、授权请求提交者。
3. **信任边界**：manifest/schema 校验边界。
4. **恶意输入最坏结果**：非法分级绕过审批（缓解：Literal 约束在 schema 层拒绝非法值）。
5. **失败是否泄露信息**：无新增错误面。

## 范围外

- `ToolEntry`/`PlanStep`/`ConnectorSpec` 的 risk_level（ADR-0029 slice 2）。
- `PlanExecutor` 审批门按 risk_level 驱动（slice 3）。
- L4 默认拒绝（slice 4）。

## 证据

- `docs/evidence/SLICE-167-risk-level-type.txt`
