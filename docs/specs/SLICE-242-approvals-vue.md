# SLICE-242 迁移审批面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第七步（面板迁移：Approvals 审批）

## 意图

把 legacy 内联壳的 Approvals（审批）面板的**只读待决列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ApprovalsView.vue`：按 `auth.hasCapability("approvals.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/approvals`，渲染表格。
2. 表格列与 legacy 等价：请求 ID（`request_id` 截前 16 位）、步骤（`step_id`）、Agent（`agent_ref.id`）、
   理由（`reason`）、提交时间（`requested_at`，`T`→空格取前 19 位）、到期（`expires_at` 经 `expiryLabel`：
   无值「no deadline」、已过期「expired」、<1h「Xm left」、否则「Xh Ym left」，<=10 分钟标 soon）。
3. `web/src/router/index.ts`：`/approvals` 路由改用 `ApprovalsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/approvals`（`approvals.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/approvals` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/ApprovalsView.vue` 引用 `/api/approvals` 与 `approvals.read` -> `test_approvals_view_fetches_approvals`
- [ ] `/approvals` 路由使用 `ApprovalsView` -> `test_approvals_route_uses_approvals_view`
- [ ] `ApprovalsView.vue` 渲染 `step_id` 与 `expires_at` 列 -> `test_approvals_view_renders_columns`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-241 状态）：无 `ApprovalsView`，`/approvals` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读待决审批摘要（请求/步骤/agent/理由/时间），无敏感载荷。
2. **调用方**：浏览器；`/api/approvals` 服务端已按 `approvals.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片不含 decide 写动作，仅列表。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 审批详情、`POST /api/approvals/{id}` 决定、历史查询（后续切片）。
- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-242-approvals-vue.txt`
