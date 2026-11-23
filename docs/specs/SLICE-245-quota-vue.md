# SLICE-245 迁移配额面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十步（面板迁移：Quota 配额）

## 意图

把 legacy 内联壳的 Quota（配额）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/QuotaView.vue`：按 `auth.hasCapability("ops.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/quota`，渲染五张卡片。
2. 卡片与 legacy 等价：窗口运行数（`window_runs`）、活跃并发（`active_leases`）、
   运行上限（`max_runs`，空显示「无限」）、并发上限（`max_concurrent`，空显示「无限」）、
   窗口秒数（`window_seconds`）。
3. `web/src/router/index.ts`：新增 `/quota` 路由用 `QuotaView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/quota`（`ops.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/quota` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/QuotaView.vue` 引用 `/api/quota` 与 `ops.read` -> `test_quota_view_fetches_quota`
- [ ] `/quota` 路由使用 `QuotaView` -> `test_quota_route_uses_quota_view`
- [ ] `QuotaView.vue` 渲染 `window_runs` 与 `max_concurrent` -> `test_quota_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-244 状态）：无 `QuotaView`，路由无 `/quota`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读配额用量摘要（运行/并发计数与上限），无敏感载荷。
2. **调用方**：浏览器；`/api/quota` 服务端已按 `ops.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含写动作。
4. **恶意输入**：卡片字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，未配置显示通用文案。

## 范围外

- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-245-quota-vue.txt`
