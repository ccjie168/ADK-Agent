# SLICE-277 页头与信息层级收口

状态: gated
依据: ADR-0041；用户要求的 Cloudflare 风格视觉改造

## 意图

把 25 个视图的标题从各自的 `<h1>` 收口到共享 `PageHeader`：

1. 每个视图（含 `PlaceholderView`）使用 `PageHeader`，页面里不再出现裸 `<h1>`；
2. 除占位页外都带一句说明，说明写在组件里，字号、间距、颜色由统一规则决定；
3. 保留各页原有主操作（注册表加载、Agent 中心租户切换、审批决定等），本切片只换页头，
   不改页面行为、接口与权限。

## 契约（先改）

无后端接口变化。

## 完成判据

- [x] 25 个视图都引用 `PageHeader` 且没有 `<h1>` -> `test_every_view_uses_the_shared_header`
- [x] 除占位页外都提供说明文字 -> `test_views_describe_themselves`
- [x] 注册表、Agent 中心、审批的主操作仍在 -> `test_pages_keep_their_primary_actions`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前：23 个视图各自渲染 `<h1>`，没有引用 `PageHeader`；3 条用例中 2 条失败。`test_pages_keep_their_primary_actions` 在基线上本来成立，作为守卫保留。

## 5 问威胁建模

1. **数据**：页面标题与说明是静态文案；不新增数据源。
2. **调用方**：浏览器；权限与接口不变。
3. **信任边界**：`PlaceholderView` 的标题来自路由名，使用 Vue 插值。
4. **恶意输入**：无 `v-html`；无用户可控 HTML。
5. **失败是否泄露信息**：不涉及。

## 范围外

- 列表空态与表格密度（SLICE-278）。
- 页头吸顶、面包屑与页面级 tab。
- 设置页的实际内容。

## 证据

- `docs/evidence/SLICE-277-page-headers.txt`
