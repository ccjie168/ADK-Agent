# SLICE-292 全部视图的手机屏适配

状态: gated
依据: 用户 2026-11-25 要求「所有的屏幕都做手机版适配」；现状只有 960px 一个断点，
抽屉导航可用，但 600px 以下没有规则，行内控件、页头、表单与聊天输入框在手机上会挤压。

## 意图

给控制台补一个 600px 的手机断点，覆盖所有 27 个路由共用的外壳与内容模式：
页头纵向排列、行内控件换行、表单单列、表格横向滚动且触屏惯性、聊天输入框贴底并避开
手势条、登录表单纵向、可点元素最小高度 40px。视图本身不逐个改结构，只补共用 CSS 与
`ChatView` 的输入行类名；个别视图若仍溢出，用截图实测逐个修。

## 契约（先改）

无后端接口变化；`docs/contracts/console.md` 的前端壳一节补一句「600px 以下手机断点」。

## 完成判据

- [ ] 600px 断点覆盖外壳、页头、行、表单与表格 -> `test_phone_breakpoint_covers_the_shell`
- [ ] 表格容器在手机上启用触屏惯性滚动 -> `test_tables_scroll_on_touch`
- [ ] 视口允许安全区（`viewport-fit=cover`） -> `test_viewport_allows_safe_areas`
- [ ] 聊天输入行贴底并避开手势条 -> `test_chat_composer_clears_the_home_bar`
- [ ] 手机端可点元素最小高度 40px -> `test_phone_tap_targets`
- [ ] 登录表单在手机上纵向排列 -> `test_login_form_stacks_on_phone`
- [ ] 390×844 实测 27 个路由无页面级横向溢出，截图留证 -> 证据
- [ ] `web/dist/` 重建
- [ ] `--full` 门禁通过

## 反例

实现前 `web/src/style.css` 没有 600px 断点，`index.html` 没有 `viewport-fit`，
`ChatView` 的输入行没有类名；六个用例在 master 上全部失败。390px 实测记录各路由的
`scrollWidth > innerWidth` 情况作为基线。

## 5 问威胁建模

1. **数据**：无新增数据；只调整样式与一个类名。
2. **调用方**：所有使用手机的登录主体。
3. **信任边界**：静态模板与样式；不放宽任何鉴权。
4. **恶意输入**：无新输入路径；`env(safe-area-inset-*)` 是浏览器提供的常量。
5. **失败是否泄露信息**：无。

## 范围外

- 深色主题、命令面板。
- 平板专属布局（960px 断点已覆盖）。
- 触屏手势（滑动切换页面等）。

## 证据

- `docs/evidence/SLICE-292-phone-layout.txt`
- `docs/evidence/ui/SLICE-292/` 关键视图 390px 截图
