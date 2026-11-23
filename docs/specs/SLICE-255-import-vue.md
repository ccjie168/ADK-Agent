# SLICE-255 迁移导入面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第二十步（面板迁移：Import 导入）

## 意图

把 legacy 内联壳的 Import（导入）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ImportView.vue`：按 `auth.hasCapability("runs.read")` 决定是否渲染，
   提供类型选择（`terminology` 术语表 / `agent` Agent 定义）、JSON 输入框与「Import」按钮。
2. 点击 Import：解析输入 JSON（非法报错），`apiFetch` POST 到 `/api/import/<kind>`，
   结果显示成功 JSON 或失败文案（`import failed (<status>)`）。
3. `web/src/router/index.ts`：新增 `/import` 路由用 `ImportView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`POST /api/import/terminology`（`semantics.write`）与 `POST /api/import/agent`（`registry.publish`）
已存在，见 `docs/contracts/console.md`。前端 `runs.read` 门控只做面板可见性，写动作仍由服务端按能力强制。

## 契约（先改）

无对外接口变化。两个 import 端点的请求/响应形状已由既有契约覆盖，本切片只消费它们。

## 完成判据

- [ ] `web/src/views/ImportView.vue` 引用 `/api/import` 与 `runs.read` -> `test_import_view_fetches_import`
- [ ] `/import` 路由使用 `ImportView` -> `test_import_route_uses_import_view`
- [ ] `ImportView.vue` 含 `terminology` 与 `agent` 类型 -> `test_import_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-254 状态）：无 `ImportView`，路由无 `/import`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：用户粘贴的 JSON 只发往本服务端 import 端点，不落本地存储。
2. **调用方**：浏览器；import 端点服务端按 `semantics.write`/`registry.publish` 门控，前端 `runs.read` 只是面板可见性。
3. **信任边界**：SPA 只做表单与转发；鉴权与写权限由服务端强制。
4. **恶意输入**：输入经 `JSON.parse` 校验，非 JSON 拒绝；请求体由服务端校验，前端无 `v-html`。
5. **失败是否泄露信息**：失败只显示状态码与服务端 error 文案，无额外敏感信息。

## 范围外

- RAG 语料导入（SLICE-227 已列为三类格式，本切片先做 terminology/agent 两类）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-255-import-vue.txt`
