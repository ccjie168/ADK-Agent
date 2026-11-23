# SLICE-248 迁移连接器面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十三步（面板迁移：Connectors 连接器）

## 意图

把 legacy 内联壳的 Connectors（连接器）面板的**只读列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ConnectorsView.vue`：按 `auth.hasCapability("connectors.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/connectors`，渲染表格。
2. 表格列与 legacy 等价：连接器 ID（`connector_id`）、租户（`tenant` 或 `global`）、类型（`kind`）、
   base URL（`base_url`）、方法（`methods` 逗号连接）、启用（`enabled` → yes/no）。
3. `web/src/router/index.ts`：新增 `/connectors` 路由用 `ConnectorsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/connectors`（`connectors.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/connectors` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/ConnectorsView.vue` 引用 `/api/connectors` 与 `connectors.read` -> `test_connectors_view_fetches_connectors`
- [ ] `/connectors` 路由使用 `ConnectorsView` -> `test_connectors_route_uses_connectors_view`
- [ ] `ConnectorsView.vue` 渲染 `connector_id` 与 `base_url` -> `test_connectors_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-247 状态）：无 `ConnectorsView`，路由无 `/connectors`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读连接器摘要（id/租户/类型/base_url/方法/启用），无敏感载荷。
2. **调用方**：浏览器；`/api/connectors` 服务端已按 `connectors.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 register/disable 写动作。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- register/disable 写动作、健康检查（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-248-connectors-vue.txt`
