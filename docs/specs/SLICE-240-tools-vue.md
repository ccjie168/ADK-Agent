# SLICE-240 迁移工具目录面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第五步（面板迁移：Tools 工具目录）

## 意图

把 legacy 内联壳的 Tools（工具目录）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ToolsView.vue`：按 `auth.hasCapability("tools.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/tools`（无 tenant 参数时服务端取调用方租户），渲染表格。
2. 表格列与 legacy 等价：工具 ID（`tool_id`）、来源（`source`）、数据分级（`data_classes` 逗号连接，空显示 `-`）、
   需审批（`requires_approval` → yes/no）、授权 Agent（`granted_agents` 的 `id@version` 逗号连接，空显示 `-`）。
3. `web/src/router/index.ts`：`/tools` 路由改用 `ToolsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/tools`（`tools.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/tools` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/ToolsView.vue` 引用 `/api/tools` 与 `tools.read` -> `test_tools_view_fetches_tools`
- [ ] `/tools` 路由使用 `ToolsView` -> `test_tools_route_uses_tools_view`
- [ ] `ToolsView.vue` 渲染 `tool_id` 与 `granted_agents` 列 -> `test_tools_view_renders_columns`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-239 状态）：无 `ToolsView`，`/tools` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读工具目录摘要（id、来源、数据分级、是否需审批、授权 agent 引用），无敏感载荷。
2. **调用方**：浏览器；`/api/tools` 服务端已按 `tools.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含写动作。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 其余面板迁移（后续切片逐个做）、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-240-tools-vue.txt`
