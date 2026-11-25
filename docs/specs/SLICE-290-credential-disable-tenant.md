# SLICE-290 凭据停用的跨租户校验

状态: gated
依据: SLICE-283 证据记录的 S-2（自定义角色获得 `connectors.manage` 后可跨租户停用凭据）

## 意图

`GET /api/credentials` 对非 admin 的显式跨租户请求返回 403 `tenant_forbidden`，但
`POST /api/credentials/{credential_id}/disable` 没有同样的检查：内置角色里 `connectors.manage`
只在 admin，所以默认配置下不可达；自定义角色库可以把 `connectors.manage` 授予其他角色，
届时该角色能停用其他租户的凭据。契约本来就写「`connectors.manage` 仅 admin」，
本切片让 disable 与列表对称。

顺序：能力 403 → 存储未配置 404 → 显式跨租户 403 → 租户/凭据 id 400 → 存储读写。
admin 跨租户行为不变。

## 契约（先改）

- `docs/contracts/console.md` 的 disable 一节：补「非 `admin` 停用其他租户返回 403 `tenant_forbidden`」。

## 完成判据

- [ ] 非 admin 跨租户停用返回 403 -> `test_disable_rejects_a_cross_tenant_caller`
- [ ] admin 跨租户停用仍可定位（404 不存在） -> `test_disable_allows_admin_cross_tenant`
- [ ] 非 admin 停用本租户凭据不受影响 -> `test_disable_keeps_the_own_tenant_path`
- [ ] 列表的跨租户 403 不回归 -> `test_list_still_rejects_a_cross_tenant_caller`

## 反例

自定义角色 `cred-admin`（`connectors.manage` + `connectors.read`）跨租户停用旧代码返回
404 `credential_not_found`（已越过授权），新代码返回 403；其余三条用例在旧代码上通过，
作为回归保护。

## 5 问威胁建模

1. **数据**：凭据元数据与启用状态；不含密文。
2. **调用方**：`connectors.manage`；非 admin 只能操作自身租户。
3. **信任边界**：角色定义来自 role store；管理员可授予 manage，但租户边界仍由接口强制。
4. **恶意输入**：跨租户 403、非法租户/id 400、不存在 404；错误码固定。
5. **失败是否泄露信息**：403 在存储读取之前，不泄露他租户是否存在该凭据。

## 范围外

- 其他带 `manage` 能力的接口（连接器、对端）的同类跨租户检查，另行评估。
- 自定义角色的审计与审批流程。

## 证据

- `docs/evidence/SLICE-290-credential-disable-tenant.txt`
