# SLICE-256 迁移 Ask AI 面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第二十一步（面板迁移：Ask AI）

## 意图

把 legacy 内联壳的 Ask AI 面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/AskAiView.vue`：按 `auth.hasCapability("runs.read")` 决定是否渲染，
   提供自然语言输入框与「Ask」按钮。
2. 点击 Ask：`apiFetch` POST 到 `/api/ask-ai`，请求体 `{text, bindings: []}`，
   结果显示成功 JSON 或失败文案（`ask failed (<status>)`）。
3. `web/src/router/index.ts`：新增 `/ask-ai` 路由用 `AskAiView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`POST /api/ask-ai` 已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`POST /api/ask-ai` 的请求/响应形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/AskAiView.vue` 引用 `/api/ask-ai` 与 `runs.read` -> `test_ask_ai_view_fetches_ask_ai`
- [ ] `/ask-ai` 路由使用 `AskAiView` -> `test_ask_ai_route_uses_ask_ai_view`
- [ ] `AskAiView.vue` 含 `text` 与 `bindings` -> `test_ask_ai_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-255 状态）：无 `AskAiView`，路由无 `/ask-ai`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：用户输入的自然语言需求只发往本服务端 `/api/ask-ai`，不落本地存储。
2. **调用方**：浏览器；`/api/ask-ai` 由服务端处理，前端 `runs.read` 只是面板可见性。
3. **信任边界**：SPA 只做表单与转发；鉴权由服务端强制。
4. **恶意输入**：文本为自由输入，仅作请求体字段发送，前端无 `v-html` 渲染。
5. **失败是否泄露信息**：失败只显示状态码与服务端 error 文案，无额外敏感信息。

## 范围外

- 其余面板迁移（Chat 为最后一步）、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-256-askai-vue.txt`
