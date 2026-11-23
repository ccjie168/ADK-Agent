# SLICE-264 Agent 中心总览（Vue，`/agents`）

状态: gated
依据: ADR-0041 阶段 2「Agent 中心总览」（诉求 2）

## 意图

把 `/agents`（目前是 `PlaceholderView`）换成 Agent 旅程视图：直接消费已有的 `GET /api/registry`
（含 `id`、`version`、`source`、`lifecycle`、`has_eval_report`、`artifact`、远端 `trust`），在前端聚合。
本切片纯前端，后端不动。

1. `web/src/views/AgentHubView.vue`：
   - 按 `registry.read` 门控；无能力显示「无访问权限」，接口失败显示错误文案。
   - **计数卡**：Agent 数（按 id 去重）、版本数、`published` / `deprecated` / `retired` 各多少、远端条目数。
   - **lifecycle 分布**：每个状态一行，条形宽度按占比（纯 CSS，不用图表库）。
   - **旅程列表**：按 `id` 分组，每组展开各版本一行：版本、lifecycle 徽标、评测（有/无）、工件（verified/
     untrusted/unsigned/unknown）、发布时间、来源（local/remote）；远端条目显示 peer 与 trust 状态。
   - 空状态：无条目时显示「暂无 Agent」。
2. `web/src/router/index.ts`：`/agents` 改用 `AgentHubView`（`PlaceholderView` 仍用于 `/settings`）。
3. 重建 `web/dist/`。

## 契约（先改）

无对外接口变化：只消费 `GET /api/registry` 现有字段（`docs/contracts/console.md` 已记录）。

## 完成判据

- [x] 视图按 `registry.read` 门控并调用 `/api/registry` -> `test_agent_hub_fetches_registry`
- [x] 视图聚合 lifecycle 计数与分布 -> `test_agent_hub_counts_lifecycle`
- [x] 视图按 id 分组展示版本、评测与工件 -> `test_agent_hub_groups_versions`
- [x] `/agents` 路由改用 `AgentHubView` -> `test_agents_route_uses_hub`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过

## 反例

基线（SLICE-263 状态）：`/agents` 用 `PlaceholderView`，无 `AgentHubView.vue`。上述用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只展示 registry 已有的元数据（id/版本/描述/时间/工件/信任状态徽标），无 manifest 内部指令内容、
   无 token。
2. **调用方**：浏览器；接口端已按 `registry.read` 强制。
3. **信任边界**：服务端仍是权威；视图只读。
4. **恶意输入**：所有值经文本插值渲染（无 `v-html`）；id/版本来自服务端校验过的 manifest。
5. **失败是否泄露信息**：失败只显示固定文案，不回显服务端错误体细节。

## 范围外

- 跨租户聚合（`?tenant=` 仍由注册表面板承担），以及「加载/卸载/打开聊天」动作（注册表面板已有）。
- lifecycle 变更动作、评测详情下钻。
- 前端单元测试框架（Vitest 仍属新 JS 依赖）。

## 证据

- `docs/evidence/SLICE-264-agent-hub.txt`
