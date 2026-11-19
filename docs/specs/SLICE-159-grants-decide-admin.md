# SLICE-159 工具授权决定收紧到 admin

状态: gated
依据: PROGRESS 缺口清单第 6 条与 2026-11-19 会话确认：`grants.decide` 的界面服务端不一致
按收紧处理，operator/ops/approver 不再拥有该能力。

## 意图

1. `_CAPABILITIES_OPERATOR` 移除 `grants.decide`；`admin` 仍隐含全部能力。
2. 界面 Approve/Deny 按钮按 `grants.decide` 显示，operator 看到的面板不再有决定按钮；
   服务端 `POST /api/tool-grants/{id}/decide` 保持 admin-only。
3. 契约与 ADR-0022 的确认记录同步；`/api/me` 的测试判据按新映射更新（用户已确认）。
4. 新增 operator 在决定接口得到 403 的用例。

## 契约（先改）

- `docs/contracts/console.md` 的角色映射与工具授权段。
- `docs/decisions/ADR-0022-self-service-composition.md` 的确认记录（角色映射可调整）。

## 完成判据

- [x] operator 的能力清单不含 `grants.decide` -> `test_operator_capabilities`
- [x] operator 调用决定接口返回 403 -> `test_operator_cannot_decide`
- [x] 全量门禁通过

## 反例

- [x] 基线 `/api/me` 给 operator 返回 `grants.decide`，界面显示决定按钮

## 5 问威胁建模

1. **数据**：能力清单、工具授权申请与决定。
2. **调用方**：operator/ops/approver 与 admin。
3. **信任边界**：OIDC/静态 token 的角色到控制台能力。
4. **恶意输入最坏结果**：低权限角色批准工具授权（缓解：能力表与服务端都只允许 admin）。
5. **失败是否泄露信息**：固定 403 `forbidden`。

## 范围外

- 工具授权申请的角色（publisher 有 `grants.request`）保持不变。
- 站内角色分配接口仍属控制面能力，另立 ADR。

## 证据

- `docs/evidence/SLICE-159-grants-decide-admin.txt`
