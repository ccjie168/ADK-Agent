# SLICE-257 迁移聊天面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 最后一步（面板迁移：Chat 聊天，SSE 流式）

## 意图

把 legacy 内联壳的 Chat（聊天）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ChatView.vue`：按 `auth.hasCapability("chat.run")` 决定是否渲染，
   `getJson` 调 `GET /api/agents` 填充 agent 选择器，提供消息输入框与发送按钮。
2. 发送：`apiFetch` POST `/api/chat/stream`，请求体 `{agent, message}`（有会话时带 `session_id`），
   用 `ReadableStream` 读 SSE 块，按空行分块解析 `event:`/`data:`；`done` 事件把 `reply` 追加为 agent 消息，
   `error` 事件把 `error` 追加为 system 消息，`progress` 忽略（只用于进度，本切片不渲染瀑布）。
3. 消息日志用数组渲染（you / agent / system 三种来源）。
4. `web/src/router/index.ts`：新增 `/chat` 路由用 `ChatView`。
5. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/agents` 与 `POST /api/chat/stream`（`chat.run` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。两个端点的请求/响应（SSE）形状已由既有契约覆盖，本切片只消费它们。

## 完成判据

- [x] `web/src/views/ChatView.vue` 引用 `/api/chat/stream` 与 `chat.run` -> `test_chat_view_fetches_chat`
- [x] `/chat` 路由使用 `ChatView` -> `test_chat_route_uses_chat_view`
- [x] `ChatView.vue` 含 `agent`、`message` 与 `reply` -> `test_chat_view_renders_fields`
- [x] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-256 状态）：无 `ChatView`，路由无 `/chat`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：用户消息只发往本服务端 `/api/chat/stream`，agent 回复与服务端事件只追加到内存日志。
2. **调用方**：浏览器；`/api/chat/stream` 服务端已按 `chat.run` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只做表单与 SSE 解析；鉴权与配额由服务端强制。
4. **恶意输入**：消息为自由文本，仅作请求体发送；SSE `data` 经 `JSON.parse` 解析，字段只做文本插值渲染，无 `v-html`。
5. **失败是否泄露信息**：失败只显示服务端 error 文案，无额外敏感信息。

## 范围外

- 进度瀑布、trace 下钻、会话切换（后续切片）、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-257-chat-vue.txt`
