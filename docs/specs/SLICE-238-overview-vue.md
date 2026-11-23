# SLICE-238 迁移总览面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第三步（面板迁移第一步：总览 Overview）

## 意图

把 legacy 内联壳的 Overview 面板迁到 Vue，行为等价（只迁渲染层，后端不动）：

1. 新增 `web/src/views/OverviewView.vue`：按 `auth.hasCapability("ops.read")` 决定是否拉取，
   用 `apiFetch`/`getJson` 调 `GET /api/overview`，渲染 `cards`（label + value，value 为 `null` 显示「未配置」）。
2. 卡片点击按 `panel` 映射到路由：`approvals`→`/approvals`、`registry`→`/registry`、`tools`→`/tools`、
   `grants`→`/grants`。
3. `web/src/router/index.ts`：`/`（home）改用 `OverviewView`；补 `/approvals` 与 `/grants` 两条占位路由。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/overview`（`ops.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/overview` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/OverviewView.vue` 引用 `/api/overview` 与 `ops.read` -> `test_overview_view_fetches_overview`
- [ ] `/` 路由使用 `OverviewView` -> `test_home_route_uses_overview_view`
- [ ] 路由含 `/approvals` 与 `/grants` -> `test_router_has_panel_routes`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-237 状态）：`web/src/views/` 只有 `PlaceholderView.vue`，无 `OverviewView`；`/` 路由用
`PlaceholderView`，路由无 `/approvals`、`/grants`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读聚合计数（待审批、已注册、工具、待处理授权），无敏感载荷。
2. **调用方**：浏览器；`/api/overview` 服务端已按 `ops.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；卡片点击只做客户端路由跳转，不触发写操作。
4. **恶意输入**：卡片 `value` 由服务端计数得到，前端只做字符串渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败静默为空，不泄露后端细节。

## 范围外

- 其余面板迁移（后续切片逐个做）、真实面板内容、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-238-overview-vue.txt`
