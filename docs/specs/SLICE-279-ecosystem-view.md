# SLICE-279 生态展示页（MCP / A2A / 连接器 / 工具）

状态: gated
依据: ADR-0041 阶段 4（诉求 4）

## 意图

新增 `web/src/views/EcosystemView.vue`（`/ecosystem`，导航「开发」组）：

1. **统一盘点**：工具目录（来源含 `mcp` / `connector` / `function` / `openapi`）、连接器
   （其中 `kind=mcp` 即 MCP 服务器）、A2A 对端。三项各自按 `tools.read` / `connectors.read` /
   `peers.read` 拉取；只有三项都无权时才整页拒绝。
2. **计数卡**：工具、MCP 工具（`source=mcp` 的静态条目，加上 `kind=mcp` 连接器产出的工具）、连接器、A2A 对端；无权限或读取失败的项显示「—」而不是 0，失败源对应的表格区块隐藏，顶部只给「X 不可用」。
3. **接入引导**：四张卡片给出可复制的真实命令——登记 MCP 连接器、把 Agent 暴露为
   streamable-http MCP 服务（含 `ADK_MCP_TOKEN` 前缀）、登记 A2A 对端、授权 A2A 对端——
   并链接到对应页面。复制用 `navigator.clipboard`，失败给固定提示。
4. **筛选**：工具表可按来源过滤（全部 / MCP / 连接器 / 函数 / OpenAPI）。
5. 空态用共享 `EmptyState`；无 `v-html`；不新增后端接口。

## 契约（先改）

无后端接口变化；只消费既有 `GET /api/tools`、`/api/connectors`、`/api/peers`。

## 完成判据

- [x] `/ecosystem` 路由与导航入口 -> `test_ecosystem_route_and_nav`
- [x] 三项数据源与对应能力 -> `test_ecosystem_reads_the_three_sources`
- [x] 只有三项都无权才整页拒绝 -> `test_ecosystem_requires_one_read_capability`
- [x] 工具可按来源过滤；MCP 筛选同时包含 `kind=mcp` 连接器产出的工具 -> `test_ecosystem_filters_tools_by_source`
- [x] 四张接入引导包含真实命令 -> `test_ecosystem_ships_onboarding_commands`
- [x] 命令可复制 -> `test_ecosystem_copies_commands`
- [x] 空态与无 `v-html` -> `test_ecosystem_uses_empty_states_and_no_raw_html`
- [x] 数据源失败时计数显示「—」、区块隐藏 -> `test_ecosystem_shows_dashes_when_a_source_fails`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前：没有 `/ecosystem` 路由与视图，`App.vue` 无入口。7 条用例全部失败。

## 5 问威胁建模

1. **数据**：工具/连接器/对端的元数据（id、来源、数据分级、授权关系、Base URL）；不含凭据值。
2. **调用方**：浏览器；服务端仍按各能力拦截，页面只决定展示。
3. **信任边界**：命令片段是静态文案；复制的文本不包含密钥，只含 `secret://` 引用占位。
4. **恶意输入**：所有字段用 Vue 插值；无 `v-html`；`clipboard` 失败只给固定提示。
5. **失败是否泄露信息**：各源失败合并成「X 不可用」；不显示服务端错误体。

## 范围外

- MCP 服务器的健康探测（连接器已有 `check` 端点，后续可接）。
- 新增后端目录或接入向导（阶段 5）。
- 对端与连接器的写操作（已有各自页面）。

## 证据

- `docs/evidence/SLICE-279-ecosystem.txt`
