# SLICE-180 SAP/MES 写 HITL 门（按风险分级推导审批）

状态: gated
依据: ADR-0031（Accepted 2026-11-19）决定 1/2 / slice 3：SAP/MES 写（L3/L4 + controlled-service）必须
HITL。把工具网关的审批门改为按 `risk_level` 推导（镜像 SLICE-169 的 `PlanStep.needs_approval`）。

## 意图

1. `ToolSpec`（tools/registry.py）增加计算属性 `needs_approval`：`requires_approval or risk_level in ("L3","L4")`。
2. `FunctionToolGateway.invoke` 的审批门改用 `spec.needs_approval`（原为 `spec.requires_approval`）。
3. `ToolEntry` 增加同义计算属性（控制台目录展示一致）。

## 契约（先改）

- 无对外 schema 变更（`ToolSpec`/`ToolEntry` 为内部类型）。

## 完成判据

- [ ] L3 工具需审批 -> `test_l3_tool_requires_approval`
- [ ] L4 工具需审批 -> `test_l4_tool_requires_approval`
- [ ] L2 工具无审批标志不需审批 -> `test_l2_tool_no_approval_without_flag`
- [ ] 审批标志本身仍生效 -> `test_requires_approval_flag_still_wins`
- [ ] 网关对 L3 工具返回 403 -> `test_gateway_requires_approval_for_l3_tool`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `ToolSpec` 无 `needs_approval`，`risk_level="L3"` 不触发审批

## 5 问威胁建模

1. **数据**：工具风险分级与审批要求。
2. **调用方**：工具网关、控制台目录视图。
3. **信任边界**：工具 schema 到网关审批门。
4. **恶意输入最坏结果**：L3/L4 连接器写绕过审批（缓解：needs_approval 从 risk_level 推导，不依赖布尔）。
5. **失败是否泄露信息**：仅标准 403 `tool_denied`，无新增错误面。

## 范围外

- 高风险写审计含 user+approver+agent+service identity（ADR-0031 决定 4，随后切片）。
- MES 双人审批（后续）。
- OBO 后置说明（slice 4）。

## 证据

- `docs/evidence/SLICE-180-hitl-gate.txt`
