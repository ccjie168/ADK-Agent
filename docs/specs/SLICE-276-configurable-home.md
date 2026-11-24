# SLICE-276 通用组件与可配置首页

状态: gated
依据: ADR-0041；用户 2026-11-24 的「页面配置」要求

## 意图

1. **通用组件**：`PageHeader.vue`（标题、说明、操作区插槽）与 `EmptyState.vue`（空态插槽），
   供后续逐页收口复用。
2. **首页** `OverviewView.vue`：
   - 页头显示标题、说明与「自定义首页」。
   - 快捷操作按能力过滤：注册 Agent（`registry.publish`）、加载版本（`registry.load`）、
     处理审批（`approvals.read`）、安全视图（`ops.read`）。
   - 指标卡沿用 `/api/overview`（`ops.read`），空时显示空态。
   - 最近活动读取 `/api/audit?limit=6`，要求 `audit.read`；无权限、失败、空列表各有固定文案。
3. **页面配置**：三个区块（快捷操作 / 指标卡 / 最近活动）可显隐，保存到
   `localStorage["adk.home.sections"]`，带「恢复默认」与「取消」；解析失败回落默认值。
4. 无 `v-html`；所有文本走 Vue 插值。

## 契约（先改）

无后端接口变化。

## 完成判据

- [x] 首页使用共享的页头与空态组件 -> `test_overview_uses_shared_components`
- [x] 区块显隐持久化到 localStorage，解析失败回落默认 -> `test_home_sections_persist_locally`
- [x] 三个区块都可以隐藏，并有恢复默认 -> `test_home_sections_can_be_hidden`
- [x] 快捷操作按能力过滤 -> `test_home_quick_actions_are_gated`
- [x] 最近活动按 `audit.read` 拉取最近 6 条 -> `test_home_loads_recent_audit`
- [x] 首页无 `v-html` -> `test_home_has_no_raw_html`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前：`OverviewView.vue` 只有 h1 与四张卡，没有 PageHeader/EmptyState、没有 localStorage、
没有最近活动、没有快捷操作。6 条用例中 5 条失败；`test_home_has_no_raw_html` 在基线上本来成立，
作为守卫保留。

## 5 问威胁建模

1. **数据**：概览计数、最近 6 条审计元数据（动作/对象/状态/时间）；不展示事件详情。
2. **调用方**：`ops.read` 与 `audit.read`；快捷操作只做导航，权限仍由目标页与服务端拦截。
3. **信任边界**：`localStorage` 是用户可控输入，只解析三个布尔值，非法值回落默认。
4. **恶意输入**：审计字段按文本插值；无 `v-html`；不把 localStorage 内容渲染成 HTML。
5. **失败是否泄露信息**：审计失败只显示固定文案；不显示服务端错误体。

## 范围外

- 拖拽排序与更多小组件（先做显隐）。
- 其他页面的页头迁移（SLICE-277）。
- 深色主题（SLICE-278 之后）。

## 证据

- `docs/evidence/SLICE-276-configurable-home.txt`
