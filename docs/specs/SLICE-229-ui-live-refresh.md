# SLICE-229 UI 实时刷新（SSE）

状态: gated
依据: ADR-0039 第二阶段候选 3（可视化实时化，触发条件已确认）；SSE 用 FastAPI 内置，无新依赖

## 意图

1. 新增 `GET /api/live`（SSE）：`text/event-stream`，每 5 秒推一个 `tick` 事件
   （`event: tick` + `{"ts": <epoch>}`），客户端断开即停止。服务端控制节奏，为后续「有变化才推」
   留出位置。
2. 前端在登录后建立 `/api/live` 的 fetch + ReadableStream 订阅（复用 `/api/chat/stream` 的模式，
   带 `Authorization` header），收到 `tick` 就刷新总览、配额、RAG、模型、语义层五个面板
   （调现有 `loadOverview` / `loadQuota` / `loadRag` / `loadModel` / `loadSemantics`）。
3. 断线自动重连（读流结束时延时重连），不重复叠加订阅。

## 契约（先改）

- `docs/contracts/console.md` 补 `GET /api/live` 一节。

## 完成判据

- [x] live 端点流式返回 tick -> `test_live_endpoint_streams_tick`
- [x] 首页含实时刷新订阅 -> `test_index_has_live_refresh`
- [x] 全量门禁通过

## 反例

- 基线 `19bdcbd`：没有 `/api/live` 路由（404），首页没有 `startLive` / `fetch("/api/live"` 订阅代码，
  两个用例分别失败。

## 5 问威胁建模

1. **数据**：tick 只含时间戳，不含业务数据；业务数据仍由各面板按能力查询。
2. **调用方**：控制台前端，经 bearer / OIDC 认证的 principal。
3. **信任边界**：principal 认证 → 建立 SSE 连接；数据可见性仍由各 `/api/*` 能力决定。
4. **恶意输入最坏结果**：占用 SSE 连接。缓解：SSE 只推心跳、频率固定（5s）、断开即停；入口限流
   已覆盖 `/api/*`。
5. **失败是否泄露信息**：无。

## 范围外

- 「有变化才推」的服务端变更检测（MVP 用固定心跳，后续再做）。
- WebSocket（SSE 已够单向推送）。
- 各面板的增量更新（MVP 收到 tick 全量刷新）。

## 证据

- `docs/evidence/SLICE-229-ui-live-refresh.txt`
