# SLICE-262 用户绑定并入能力解析

状态: gated
依据: ADR-0041 阶段 1「用户绑定」+ SLICE-259 store + SLICE-260 运行时解析

## 意图

SLICE-259 加的绑定 store 目前只是存着不生效。本切片让 `_caps_for` 把用户的绑定角色并入 token 角色，
使「给某个用户绑 operator」真正改变其能力。

1. `_caps_for(caller)` 的有效角色集 = `caller.roles ∪ binding(tenant, subject).roles`：
   - `user_binding_store` 未配置时行为与现在完全一致（只看 token 角色）。
   - 配置后先读绑定；绑定不存在视为无附加角色。
   - 合并后仍是「角色名 → role store 定义的能力并集」，未定义角色贡献空集，空则回落基础能力。
2. **fail-closed**：
   - 绑定 store 读失败 → 记日志，**只用 token 角色**继续解析（不因绑定故障剥夺 token 已有权限，
     也不因故障扩大权限）；若此时 role store 也失败，则照旧回落基础能力。
   - 绑定里出现白名单外的角色名（只能来自被篡改的存储，写入时 pydantic 已校验）会让整条绑定读取失败，
     按上一条回落到 token 角色，不报错、不扩权。
3. 绑定只在租户内生效：读取用 `caller.tenant`，不接受请求参数影响。
4. 审计：解析过程不写审计（只读路径，保持现状）；绑定变更的审计已在 SLICE-261。

## 契约（先改）

`docs/contracts/console.md` 的「能力来源」一节补充：有效角色 = token 角色 ∪ 租户内用户绑定角色；
绑定 store 不可用时只用 token 角色；`?tenant=` 等请求参数不影响能力解析。

## 完成判据

- [x] 未配置绑定 store 时能力与改动前逐项相同 -> `test_capabilities_unchanged_without_binding_store`
- [x] 绑定角色并入 token 角色取并集 -> `test_binding_roles_join_token_roles`
- [x] 绑定在别的租户不生效 -> `test_binding_is_tenant_scoped`
- [x] 并集不会削减 token 已有能力 -> `test_union_never_drops_token_capabilities`
- [x] 绑定 store 读失败时回落到 token 角色（不剥夺、不放行） -> `test_binding_failure_keeps_token_roles`
- [x] 绑定里未定义的角色不加任何能力 -> `test_binding_with_undefined_role_adds_nothing`
- [x] 端到端：绑定 operator 的 base 用户可读审计（token 只有 base） -> `test_bound_user_gains_panel_access`
- [x] `--full` 门禁通过

## 反例

基线（SLICE-261 状态）：`build_console_app` 接受 `user_binding_store` 但 `_caps_for` 完全不读它，
绑定 operator 的 base 用户仍拿不到 `audit.read`。上述用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：绑定角色是授权配置；读取不返回绑定内容。
2. **调用方**：任何持 token 的浏览器；绑定由 admin 通过 SLICE-261 接口写入。
3. **信任边界**：解析在服务端每请求执行，绑定按 `caller.tenant` 查，请求方无法指定租户。
4. **恶意输入**：绑定在写入时已用 pydantic 校验（角色名白名单）；解析时防御性忽略非法名。
5. **失败是否泄露信息**：绑定读失败只记类型级日志，不返回绑定内容，也不改变 403 响应体。

## 风险

合并 token 角色与绑定角色意味着「OIDC 发得越多的角色 + 绑定越多，权限越大」，二者都是加法的；
撤销需要同时动 OIDC 与绑定。绑定 store 故障时保留 token 角色，是为了不让一次存储抖动把所有人
踢回基础能力；若希望故障时更严格，可另设开关，本切片不做。

## 范围外

- 前端「用户/角色」面板（SLICE-263）。
- 绑定角色的优先级/冲突策略（当前是并集，没有 deny 语义）。
- 把绑定接入 MCP/A2A 等服务面（它们用各自的身份源，不经控制台能力表）。

## 证据

- `docs/evidence/SLICE-262-binding-capabilities.txt`
