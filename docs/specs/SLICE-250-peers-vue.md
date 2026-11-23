# SLICE-250 迁移对端面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十五步（面板迁移：Peers 对端）

## 意图

把 legacy 内联壳的 Peers（对端）面板的**只读列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/PeersView.vue`：按 `auth.hasCapability("peers.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/peers`，渲染表格。
2. 表格列与 legacy 等价：对端 ID（`peer.peer_id`）、租户（`peer.tenant`）、主体（`peer.subject`）、
   类型（`peer.kind`）、启用（`peer.enabled` → yes/no）、授权（`grants` 的 `agent_id:actions` 逗号连接，空显示 `-`）。
3. `web/src/router/index.ts`：新增 `/peers` 路由用 `PeersView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/peers`（`peers.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/peers` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/PeersView.vue` 引用 `/api/peers` 与 `peers.read` -> `test_peers_view_fetches_peers`
- [ ] `/peers` 路由使用 `PeersView` -> `test_peers_route_uses_peers_view`
- [ ] `PeersView.vue` 渲染 `peer_id` 与 `grants` -> `test_peers_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-249 状态）：无 `PeersView`，路由无 `/peers`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读对端身份与授权摘要（id/租户/主体/类型/启用/授权），无敏感载荷。
2. **调用方**：浏览器；`/api/peers` 服务端已按 `peers.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 register/grant/revoke 写动作。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- register/grant/revoke/disable 写动作（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-250-peers-vue.txt`
