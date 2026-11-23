# SLICE-247 迁移语义层面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十二步（面板迁移：Semantics 语义层）

## 意图

把 legacy 内联壳的 Semantics（语义层）面板的**只读术语表列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/SemanticsView.vue`：按 `auth.hasCapability("ops.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/semantics`，为每个术语表渲染一张卡片。
2. 卡片与 legacy 等价：标签「术语表」，值 `scheme_id (N 概念)`（N = `concepts` 长度）。
3. `web/src/router/index.ts`：新增 `/semantics` 路由用 `SemanticsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/semantics`（`ops.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/semantics` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/SemanticsView.vue` 引用 `/api/semantics` 与 `ops.read` -> `test_semantics_view_fetches_semantics`
- [ ] `/semantics` 路由使用 `SemanticsView` -> `test_semantics_route_uses_semantics_view`
- [ ] `SemanticsView.vue` 渲染 `scheme_id` 与 `concepts` -> `test_semantics_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-246 状态）：无 `SemanticsView`，路由无 `/semantics`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读术语表摘要（scheme_id 与概念数），无敏感载荷。
2. **调用方**：浏览器；`/api/semantics` 服务端已按 `ops.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 route 回放写动作。
4. **恶意输入**：卡片字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- `/api/semantics/route` 路由回放（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-247-semantics-vue.txt`
