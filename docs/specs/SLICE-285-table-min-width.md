# SLICE-285 表格容器的窄屏最小宽度

状态: gated
依据: PROGRESS 控制台视觉残余（`.table-wrap` 无可滚动的最小宽度）

## 意图

列表页的 `.table-wrap` 只是 `overflow-x: auto`，窄屏上表格会一直压缩、单元格文字逐行换行，
既难读也看不到滚动条。给容器内的表格一个最小宽度（720px），窄屏保持横向滚动，桌面不受影响。

只改 CSS，不改数据或组件结构；视觉证据用 480px 宽的无头浏览器截图。

## 契约（先改）

无后端接口变化；`docs/contracts/console.md` 的前端壳不描述具体像素尺寸，无需改。

## 完成判据

- [ ] `.table-wrap table` 设置 `min-width: 720px` -> `test_table_wrapper_sets_a_min_width`
- [ ] 五个列表页仍使用 `.table-wrap` -> `test_list_views_wrap_tables`
- [ ] `web/dist/` 重建，480px 截图显示横向滚动容器 -> 证据
- [ ] `--full` 门禁通过

## 反例

实现前 CSS 没有 `.table-wrap table` 规则，第一条用例失败；第二条在旧代码上通过，作为视图
仍使用共享容器的回归保护。

## 5 问威胁建模

1. **数据**：无新增数据；只影响表格布局。
2. **调用方**：所有能看列表页的主体。
3. **信任边界**：纯静态样式。
4. **恶意输入**：不渲染新内容；表格文本仍走 Vue 插值。
5. **失败是否泄露信息**：无。

## 范围外

- 深色主题、命令面板、移动端侧栏交互（既有抽屉）。
- 每页单独调整列宽或隐藏列。

## 证据

- `docs/evidence/SLICE-285-table-min-width.txt`
- `docs/evidence/ui/SLICE-285-tools-narrow.png`
