# SLICE-261 角色与用户管理接口（/api/roles、/api/users）

状态: gated
依据: ADR-0041 阶段 1 第 3 节「管理界面」与「安全边界」（已确认新增 `roles.read`/`roles.manage` 能力名）

## 意图

在 SLICE-258/259/260 的 store 与运行时解析之上，加管理面接口（前端面板留到 SLICE-262）：

1. **能力词表**：`CAPABILITIES_ALL` 新增 `roles.read`、`roles.manage`。两项目前只发给 `admin`
   （`CAPABILITIES_OPERATOR`/`CAPABILITIES_PUBLISHER`/`CAPABILITIES_BASE` 不变）。
2. `console` 接线：`--user-binding-store-dir` / `--user-binding-store-db`（env
   `USER_BINDING_DATABASE_URL`），语义与角色 store 一致；`build_console_app`/`run_console` 新增
   `user_binding_store` 参数。
3. 角色接口：
   - `GET /api/roles`（`roles.read`）→ `{"roles": [...]}`，每项 name/capabilities/builtin/description。
   - `PUT /api/roles/{name}`（`roles.manage`）→ body `{capabilities: [...], description?}`，写定义并审计
     `role.define`；`name` 走白名单，非法 400，store 冲突（已有不同定义）409 `role_conflict`，
     store 不可用 503 `role_store_unavailable`。
   - `DELETE /api/roles/{name}`（`roles.manage`）→ 不存在 404；内置角色拒绝 409 `builtin_role_immutable`；
     成功审计 `role.remove`。
   - 未配置 role store 时三个接口都 404 `role_store_not_configured`（能力检查先于配置检查）。
4. 用户绑定接口：
   - `GET /api/users`（`roles.read`）→ 当前租户的绑定列表（`tenant` 取调用方租户）。
   - `PUT /api/users/{subject}`（`roles.manage`）→ body `{roles: [...]}`，写绑定并审计 `user.bind`；
     非法 400，冲突 409 `user_binding_conflict`，store 不可用 503。
   - `DELETE /api/users/{subject}`（`roles.manage`）→ 不存在 404，成功审计 `user.unbind`。
   - 未配置 user binding store 时三个接口 404 `user_binding_store_not_configured`。
5. 租户边界：**非 admin 只能看/改自己租户的绑定**；`admin` 可用 `?tenant=` 指定。能力检查一律先于
   `?tenant=` 解析与请求体解析（与既有写路径一致）。
6. 审计：`AuditEvent(action="role.define"|"role.remove"|"user.bind"|"user.unbind")`，
   `target` 为角色名或 `<tenant>/<subject>`，审计失败不回滚（与既有面板写路径一致，记日志）。

## 契约（先改）

`docs/contracts/console.md` 新增「角色与用户管理」一节：四个端点的请求/响应形状、所需能力、
错误码（400/403/404/409/503）与错误体，以及租户可见性规则。

## 完成判据

- [x] 无 `roles.read` 的调用方被 403 拒绝（能力先于配置检查） -> `test_roles_list_requires_capability`
- [x] admin 可列出与定义角色，写审计 `role.define` -> `test_admin_defines_role_and_audits`
- [x] 非 admin 无 `roles.manage` 不能写角色 -> `test_role_write_requires_capability`
- [x] 内置角色不可删除（409），未知角色 404 -> `test_builtin_role_is_immutable`、`test_remove_unknown_role_is_404`
- [x] 编辑内置角色保留 builtin 标记，之后仍不可删 -> `test_editing_a_builtin_keeps_it_immutable`
- [x] 未配置 store 返回 404 `role_store_not_configured` -> `test_roles_api_requires_store`
- [x] 用户绑定读写与租户隔离 -> `test_admin_binds_user_and_audits`、`test_user_bindings_are_tenant_scoped`
- [x] 新增两个能力后 admin 全量清单更新（仅新增，不放宽） -> `test_admin_has_role_management_capabilities`
- [x] `--full` 门禁通过

## 反例

基线（SLICE-260 状态）：无 `/api/roles`、`/api/users` 路由，`CAPABILITIES_ALL` 无 `roles.read`/
`roles.manage`，`build_console_app` 无 `user_binding_store`。上述用例在未改实现时全部失败（404 / KeyError / TypeError）。

## 5 问威胁建模

1. **数据**：角色能力集合与用户绑定是授权配置；接口只返回定义，不返回任何密钥或 token。
2. **调用方**：浏览器 bearer/OIDC token；`roles.manage` 默认只有 admin 拥有。
3. **信任边界**：所有写接口在服务端按能力检查，先于 body 解析；`?tenant=` 与路径 `subject` 均校验。
4. **恶意输入**：pydantic 校验 name/capabilities/roles/subject；`subject` 落盘用 sha256（SLICE-259），
   路径不存在穿越面；能力名白名单阻止拼写错误静默扩大权限。
5. **失败是否泄露信息**：store 失败只返回固定错误码并记类型级日志；403 仍是固定 `forbidden`。

## 风险

`roles.manage` 可以给任意角色授予任意能力，等价于完整授权面。缓解：默认只有 admin 拥有；
删除内置角色被拒绝；每次写都审计。**新增能力名属于能力词表扩展，已在会话中确认**。

## 范围外（后续切片）

- SLICE-262：`_caps_for` 把用户绑定并入 token 角色集（租户维度，绑定 store 不可用时同样的 fail-closed），
  让绑定真正生效；需要单独设计 token 角色与绑定角色的合并顺序并测试。
- SLICE-263：前端「用户/角色」面板（Vue）。
- 给非 admin 角色默认授予 `roles.read`（保持 admin-only 起步）。

## 证据

- `docs/evidence/SLICE-261-roles-users-api.txt`
