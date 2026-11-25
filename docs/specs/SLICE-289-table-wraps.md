# SLICE-289 其余视图的表格并入共享滚动容器

状态: gated
依据: SLICE-288 证据记录的新观察（9 个视图的表格未包在 `.table-wrap`）

## 意图

SLICE-285 给 `.table-wrap table` 加了 720px 最小宽度，但当时只有五个列表页使用该容器；
Agent 中心、审批、连接器、凭据、生态（三张表）、授权、总览、角色、用户共 9 个视图的 `<table>`
仍在容器外，窄屏继续压缩换行。本切片把这些表格统一包进 `<div class="table-wrap">`，
文字与数据不变。

## 契约（先改）

无后端接口变化；`docs/contracts/console.md` 不描述具体像素或容器结构，无需改。

## 完成判据

- [ ] 14 个含表格的视图都使用 `.table-wrap` -> `test_list_views_wrap_tables`
- [ ] 每个视图的容器数不少于表格数 -> `test_every_view_table_is_wrapped`
- [ ] `.table-wrap table` 的最小宽度规则仍在 -> `test_table_wrapper_sets_a_min_width`
- [ ] `web/dist/` 重建，480px 截图确认角色表横向滚动 -> 证据
- [ ] `--full` 门禁通过

## 反例

实现前，把 9 个视图临时换回 master 版本：
`test_list_views_wrap_tables` 与 `test_every_view_table_is_wrapped` 失败，最小宽度用例通过。

## 5 问威胁建模

1. **数据**：无新增数据；只调整包裹元素。
2. **调用方**：所有能看这些页面的主体。
3. **信任边界**：静态模板与样式。
4. **恶意输入**：表格文本仍走 Vue 插值，无 `v-html`。
5. **失败是否泄露信息**：无。

## 范围外

- 新增列、改排序或隐藏列。
- 深色主题与命令面板。

## 证据

- `docs/evidence/SLICE-289-table-wraps.txt`
- `docs/evidence/ui/SLICE-289-roles-narrow.png`
