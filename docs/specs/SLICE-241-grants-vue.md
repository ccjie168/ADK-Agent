# SLICE-241 迁移工具授权面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第六步（面板迁移：Grants 工具授权）

## 意图

把 legacy 内联壳的 Grants（工具授权）面板的**只读列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/GrantsView.vue`：按 `auth.hasCapability("grants.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/tool-grants`（无 tenant 参数时服务端取调用方租户），渲染表格。
2. 表格列与 legacy 等价：工具 ID（`tool_id`）、Agent（`agent_id`）、版本（`version`）、状态（`status`，
   已批准且 24 小时内到期的追加 `expiring` 徽标）、到期时间（`expires_at`，`T`→空格取前 19 位）。
3. `web/src/router/index.ts`：`/grants` 路由改用 `GrantsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/tool-grants`（`grants.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/tool-grants` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/GrantsView.vue` 引用 `/api/tool-grants` 与 `grants.read` -> `test_grants_view_fetches_grants`
- [ ] `/grants` 路由使用 `GrantsView` -> `test_grants_route_uses_grants_view`
- [ ] `GrantsView.vue` 渲染 `agent_id` 与 `expires_at` 列 -> `test_grants_view_renders_columns`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-240 状态）：无 `GrantsView`，`/grants` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读工具授权请求摘要（工具/agent/版本/状态/到期时间），无敏感载荷。
2. **调用方**：浏览器；`/api/tool-grants` 服务端已按 `grants.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片不含 request/decide 写动作，仅列表。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- `/api/tool-grants/usage` 用量表与 request/decide 写动作（后续切片）。
- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-241-grants-vue.txt`
