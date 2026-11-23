# SLICE-252 迁移会话面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十七步（面板迁移：Sessions 会话）

## 意图

把 legacy 内联壳的 Sessions（会话）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/SessionsView.vue`：按 `auth.hasCapability("sessions.read")` 决定是否拉取。
   先 `getJson` 调 `GET /api/agents` 填充 agent 选择器，选中后 `getJson` 调
   `GET /api/sessions?agent=<name>` 渲染会话表格。
2. 表格列与 legacy 等价：会话 ID（`session_id`）、最后更新（`last_update_time`，`T`→空格取前 19 位）。
3. `web/src/router/index.ts`：新增 `/sessions` 路由用 `SessionsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/agents` 与 `GET /api/sessions`（`sessions.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。两个端点的返回形状已由既有契约覆盖，本切片只消费它们。

## 完成判据

- [ ] `web/src/views/SessionsView.vue` 引用 `/api/sessions` 与 `sessions.read` -> `test_sessions_view_fetches_sessions`
- [ ] `/sessions` 路由使用 `SessionsView` -> `test_sessions_route_uses_sessions_view`
- [ ] `SessionsView.vue` 渲染 `session_id` 与 `last_update_time` -> `test_sessions_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-251 状态）：无 `SessionsView`，路由无 `/sessions`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读会话 ID 与更新时间，无敏感载荷。
2. **调用方**：浏览器；`/api/sessions` 服务端已按 `sessions.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含会话切换写动作。
4. **恶意输入**：agent 名来自 `/api/agents`（服务端来源），`session_id`/时间只做文本插值，无 `v-html`。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 点击会话切换到聊天（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-252-sessions-vue.txt`
