# SLICE-278 空态、表格滚动与令牌化收口

状态: gated
依据: ADR-0041；Cloudflare 风格视觉改造

## 意图

1. **空态**：运行、计划、会话、工具、对端、审计六个列表页在数据为空时使用共享 `EmptyState`，
   不再把「暂无X」塞进表格行或普通段落；无权限、错误、空三种状态各自独立。
2. **窄屏表格**：五个表格页把 `<table>` 包进 `.table-wrap`（`overflow-x: auto`），窄屏横向滚动
   而不是挤压列。
3. **字号层级**：`未配置` 这类文本型指标改用 `.stat-value-text`（16px、次要色），数字仍是 28px。
4. **表单工具条**：Agent 中心的租户输入与按钮收进 `.toolbar`（最大 520px），不再拉满整行。
5. **徽章令牌化**：`.badge` / `.expiry` 的硬编码绿色与黄色换成 `--success-soft/--success`、
   `--warning-soft/--warning`、`--danger-soft/--danger`。

只改模板与样式，不动脚本逻辑、接口与权限。

## 契约（先改）

无后端接口变化。

## 完成判据

- [x] 六个列表页使用 `EmptyState` -> `test_list_pages_use_empty_state`
- [x] 五个表格页用 `.table-wrap` 包裹，样式存在 -> `test_tables_scroll_on_narrow_screens`
- [x] 文本型指标使用 `stat-value-text` -> `test_text_stat_values_scale_down`
- [x] 徽章与到期标记使用状态令牌，不再有旧绿 `#e6f5ea` -> `test_badges_use_tokens`
- [x] Agent 中心租户表单使用 `.toolbar` -> `test_agent_hub_uses_a_toolbar`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前：六个列表页的空态是表格行或普通段落、没有 `EmptyState`；表格没有 `.table-wrap`；
`.stat-value-text`、`.toolbar` 不存在；徽章仍是 `#e6f5ea`。五条用例全部失败。

## 5 问威胁建模

1. **数据**：空态文案是静态文案；不新增数据源。
2. **调用方**：浏览器；权限与接口不变。
3. **信任边界**：无新输入。
4. **恶意输入**：无 `v-html`；模板文本走插值。
5. **失败是否泄露信息**：错误仍显示固定文案，不显示服务端错误体。

## 范围外

- 深色主题与页面级 tab。
- 审批历史与详情页。
- 移动端导航的进一步优化。

## 证据

- `docs/evidence/SLICE-278-empty-states.txt`
