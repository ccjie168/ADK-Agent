# SLICE-170 授权决策点 L4 默认拒绝

状态: gated
依据: ADR-0029（Accepted 2026-11-19）决定 5 / slice 4：L4 拒绝在授权决策点执行（ADR-0028 服务端），
不在工具处理器里补丁式拦截；MVP 内先默认拒绝，特批流程与特批审计后置。

## 意图

1. `GrantPolicyEngine.decide` 对 manifest 授权（`ToolGrant`）中 `risk_level == "L4"` 的工具默认拒绝，
   返回 `decision="deny"`、`error_code="l4_default_deny"`。
2. 非 L4（L1/L2/L3/None）的授权维持现状 `allow`。
3. 同一 `tool_id` 存在多个授权时取最高风险等级（fail-closed）。
4. `docs/contracts/tool_gateway.md` 记录 L4 默认拒绝语义。

## 契约（先改）

- `docs/contracts/tool_gateway.md`：补充 L4 默认拒绝；`GrantPolicyEngine` 拒绝时仍映射 403 `tool_denied`。

## 完成判据

- [ ] L4 manifest 授权默认拒绝 -> `test_l4_grant_is_denied_by_default`
- [ ] L3 manifest 授权仍允许 -> `test_l3_grant_is_allowed`
- [ ] L1/L2/None 授权仍允许 -> `test_non_l4_grant_is_allowed`
- [ ] 同一工具 L4 与 L1 并存取最高风险拒绝 -> `test_l4_wins_over_lower_risk`
- [ ] 工具网关对 L4 工具调用返回 403 -> `test_gateway_denies_l4_tool`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `risk_level="L4"` 的授权仍被 `allow`（`GrantPolicyEngine` 忽略 risk_level）

## 5 问威胁建模

1. **数据**：manifest 工具授权的 risk_level 与授权决策。
2. **调用方**：工具网关 `/v1/invoke`、控制台 in-process 工具守卫（都走 `GrantPolicyEngine`）。
3. **信任边界**：manifest schema 到授权决策点。
4. **恶意输入最坏结果**：L4 工具被静默放行（缓解：决策点集中 deny，不依赖工具处理器）。
5. **失败是否泄露信息**：仅标准 403 `tool_denied`，无新增错误面。

## 范围外

- L4 特批流程与特批审计（ADR-0029 slice 4 后置部分，需独立特批流程与审计）。
- 临时授权（`ToolGrantStore` overlay）的风险分级：其 `active()` 只返回 bool，无 risk_level，另行切片。

## 证据

- `docs/evidence/SLICE-170-l4-default-deny.txt`
