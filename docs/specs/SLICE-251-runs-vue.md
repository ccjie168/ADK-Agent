# SLICE-251 迁移运行面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十六步（面板迁移：Runs 运行）

## 意图

把 legacy 内联壳的 Runs（运行）面板的**只读列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/RunsView.vue`：按 `auth.hasCapability("runs.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/runs?limit=50`，渲染表格。
2. 表格列与 legacy 等价：运行 ID（`run_id` 截前 12 位）、Agent（`agent_id`）、状态（`status`）、
   开始时间（`started_at`，`T`→空格取前 19 位）、延迟（`latency_ms`，空显示 `-`，否则 `Xms`）、
   成本（`cost_usd`，空显示 `-`）、事件数（`events`）。
3. `web/src/router/index.ts`：新增 `/runs` 路由用 `RunsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/runs`（`runs.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/runs` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/RunsView.vue` 引用 `/api/runs` 与 `runs.read` -> `test_runs_view_fetches_runs`
- [ ] `/runs` 路由使用 `RunsView` -> `test_runs_route_uses_runs_view`
- [ ] `RunsView.vue` 渲染 `run_id` 与 `latency_ms` -> `test_runs_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-250 状态）：无 `RunsView`，路由无 `/runs`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读运行摘要（id/agent/状态/时间/延迟/成本/事件数），无敏感载荷。
2. **调用方**：浏览器；`/api/runs` 服务端已按 `runs.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 trace 下钻写动作。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 点击行加载 trace 详情（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-251-runs-vue.txt`
