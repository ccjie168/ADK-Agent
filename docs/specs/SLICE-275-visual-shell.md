# SLICE-275 视觉基座：设计令牌、应用外壳与分组导航

状态: gated
依据: ADR-0041；用户 2026-11-24 要求参考 Cloudflare 仪表盘的视觉与页面组织

## 意图

把控制台的视觉基座换成可扩展的一套：

1. **设计令牌** `web/src/styles/tokens.css`：canvas/card/border/text/accent/状态色、4–48px 间距、
   字号、圆角、阴影、顶栏高度、侧栏宽度、内容最大宽度；旧变量（`--bg/--panel/--line/--ink`）
   作为别名保留，避免一次性改所有视图。主色用可过 AA 的深橙（白字 5.18:1）。
2. **应用外壳** `App.vue`：顶栏（品牌、租户、主体、退出）、分组侧栏（概览/运行/治理/开发/设置）、
   导航图标、窄屏抽屉、登录页与加载态。补齐此前只靠 URL 才能进入的面板入口。
3. **能力就绪门控**：`auth` store 增加 `ready`（配置加载完）与 `resolved`（`/api/me` 结束）；
   `RouterView` 只在 `resolved` 后挂载。刷新、token 登录、OIDC 回调三条路径都要等 `/api/me`，
   修掉「视图在能力到达前挂载、`denied` 直接 return、页面永久空白」的竞态；401 清 token，
   网络失败显示固定提示。
4. **控件基线** `style.css`：按钮、输入、表格、卡片、焦点环与响应式断点统一走令牌。

不新增依赖；图标是内联 SVG。

## 契约（先改）

无后端接口变化。前端不新增对外契约。

## 完成判据

- [x] 令牌覆盖画布、主色、文字、边框、顶栏与侧栏尺寸 -> `test_shell_tokens_cover_the_surface_scale`
- [x] 导航覆盖现有全部面板路由 -> `test_shell_navigation_covers_every_panel`
- [x] `/api/me` 返回前不挂载视图 -> `test_shell_waits_for_capabilities`
- [x] 刷新、token 登录、OIDC 回调三条路径都等 `/api/me` -> `test_auth_store_holds_the_shell_for_every_login_path`
- [x] 401 清 token、网络失败有固定提示 -> `test_auth_store_clears_a_rejected_token`
- [x] 正文与辅助文字的对比度过 AA -> `test_tokens_meet_text_contrast`
- [x] 顶栏显示租户与主体 -> `test_shell_shows_the_caller_identity`
- [x] 窄屏有导航开关 -> `test_shell_has_a_mobile_navigation_toggle`
- [x] 样式使用令牌且不再出现旧主色 -> `test_shell_styles_use_tokens`
- [x] 外壳无 `v-html` -> `test_shell_has_no_raw_html`
- [x] 导航项使用内联 SVG 图标 -> `test_shell_has_navigation_icons`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前：`tokens.css` 不存在；`App.vue` 是 10 个平铺链接、无 ready 门控、无租户/主体、
无移动开关；`style.css` 不含 `var(--canvas)`。8 条用例中 7 条失败；`test_shell_has_no_raw_html`
在基线上本来成立，作为守卫保留（基线无 `v-html`，不构成本切片的红测）。

## 5 问威胁建模

1. **数据**：主体、租户、能力名；不新增数据源。
2. **调用方**：浏览器；服务端权限不变，导航只影响可见入口，深链仍由服务端与视图门控拦截。
3. **信任边界**：无新输入；租户与主体来自 `/api/me`，用文本插值渲染。
4. **恶意输入**：无 `v-html`；错误与主体文本按 Vue 转义。
5. **失败是否泄露信息**：加载失败只显示固定文案；不在外壳里回显服务端错误体。

## 范围外

- 通用组件库与首页改造（SLICE-276）。
- 逐页视觉收口（SLICE-277）。
- 深色主题（令牌已预留，后续单独切片）。
- 命令面板（Cmd/Ctrl+K）。

## 证据

- `docs/evidence/SLICE-275-visual-shell.txt`
