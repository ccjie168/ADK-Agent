# SLICE-263 用户/角色管理面板（Vue）

状态: gated
依据: ADR-0041 阶段 1 第 3 节「管理界面」（诉求 1+6）

## 意图

在 SLICE-261 的管理接口之上加 Vue 面板：admin 可在界面里查看/新增/编辑/删除角色，查看/绑定/解绑用户。

1. `web/src/views/RolesView.vue`：
   - 按 `roles.read` 门控；无能力显示「无访问权限」。
   - `GET /api/roles` 渲染角色表（名称 / 能力数 / 内置标记 / 描述），选中一行显示其能力清单。
   - 新增/编辑：名称输入（编辑时锁定）+ 能力多选（复选框列出 `CAPABILITIES` 常量）+ 描述 → `PUT /api/roles/{name}`。
   - 删除：内置角色不显示删除按钮；非内置可删 → `DELETE /api/roles/{name}`。
   - 写按钮按 `roles.manage` 显示。
2. `web/src/views/UsersView.vue`：
   - 按 `roles.read` 门控；`GET /api/users` 渲染绑定表（租户 / 主体 / 角色）。
   - 绑定/改绑：主体输入 + 角色多选 → `PUT /api/users/{subject}`；解绑 → `DELETE /api/users/{subject}`。
   - 写按钮按 `roles.manage` 显示。
3. 路由：新增 `/roles` 与 `/users`，侧边导航加两项（与其他导航一致，无条件显示；
   无权限时由面板本身显示「无访问权限」）。
4. 能力词表常量在 `web/src/api/capabilities.ts` 里维护一份（与后端 `CAPABILITIES_ALL` 同名单），用于多选框。

后端无改动。

## 契约（先改）

无对外接口变化；两个面板只消费 SLICE-261 已记录在 `docs/contracts/console.md` 的端点。

## 完成判据

- [x] RolesView 按 `roles.read` 门控并调用 `/api/roles` -> `test_roles_view_fetches_roles`
- [x] RolesView 写操作按 `roles.manage` 门控并 PUT/DELETE 角色 -> `test_roles_view_writes_roles`
- [x] UsersView 按 `roles.read` 门控并调用 `/api/users` -> `test_users_view_fetches_users`
- [x] UsersView 写操作 PUT/DELETE 用户绑定 -> `test_users_view_writes_bindings`
- [x] 路由含 `/roles`、`/users` 且侧边导航有入口 -> `test_router_has_roles_and_users`
- [x] 能力常量清单与后端一致（26+2 项全含） -> `test_capabilities_constant_matches_backend`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过

## 反例

基线（SLICE-262 状态）：无 `RolesView.vue` / `UsersView.vue` / `capabilities.ts`，路由无 `/roles`、`/users`。
上述用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：面板只显示角色定义与绑定（无密钥、无 token）。
2. **调用方**：浏览器；接口端已按 `roles.read`/`roles.manage` 强制，前端门控只影响可见性。
3. **信任边界**：服务端仍是权威；面板不能扩大权限。
4. **恶意输入**：角色/描述/主体都经服务端 pydantic 校验；前端只做必填检查，渲染用文本插值（无 `v-html`）。
5. **失败是否泄露信息**：失败只显示服务端固定错误码文案。

## 范围外

- 能力清单按角色高亮差异、批量绑定、审计历史视图。
- 前端单元测试框架（Vitest 仍是新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-263-roles-panel.txt`
