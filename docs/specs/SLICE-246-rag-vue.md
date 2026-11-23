# SLICE-246 迁移 RAG 面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十一步（面板迁移：RAG 检索）

## 意图

把 legacy 内联壳的 RAG（检索）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/RagView.vue`：按 `auth.hasCapability("ops.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/rag`，渲染三张卡片。
2. 卡片与 legacy 等价：最近检索（`recent_retrievals`）、最近 top_k（`last_top_k`，空显示「—」）、
   最近返回（`last_returned`，空显示「—」）。
3. `web/src/router/index.ts`：新增 `/rag` 路由用 `RagView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/rag`（`ops.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/rag` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/RagView.vue` 引用 `/api/rag` 与 `ops.read` -> `test_rag_view_fetches_rag`
- [ ] `/rag` 路由使用 `RagView` -> `test_rag_route_uses_rag_view`
- [ ] `RagView.vue` 渲染 `recent_retrievals` 与 `last_returned` -> `test_rag_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-245 状态）：无 `RagView`，路由无 `/rag`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读检索摘要（最近检索数、top_k、返回数），无敏感载荷。
2. **调用方**：浏览器；`/api/rag` 服务端已按 `ops.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含写动作。
4. **恶意输入**：卡片字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-246-rag-vue.txt`
