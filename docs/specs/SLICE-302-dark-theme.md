# SLICE-302 控制台深色主题

状态: active
依据: 视觉改造遗留项「深色主题仍未做」（PROGRESS 第 16 条）

## 意图

Vue 控制台支持浅色/深色两套主题：首次访问跟随系统偏好，手动切换后记住选择；
切换按钮在顶栏，所有 27 个页面与手机布局共用同一套 token，不出现写死的浅色背景。

## 契约（先改）

无后端接口变化。前端约定：

- `<html data-theme="light|dark">` 是唯一开关；首次渲染前由 `web/index.html` 内联脚本
  按 `localStorage["adk_theme"]` 或 `prefers-color-scheme` 设置，避免闪烁。
- 顶栏按钮写回 `localStorage` 与 `data-theme`，`aria-pressed` 反映当前是否深色。
- 深色值全部落在 `tokens.css` 的 `[data-theme="dark"]` 覆盖块；`style.css` 不再写死颜色。
- 手册 `docs/guides/console-ui.html` 的设置一节说明切换方式与记忆行为。

## 完成判据

- [ ] 深色 token 覆盖块存在且不改结构尺寸 -> `test_dark_tokens_override_colors`
- [ ] 顶栏按钮切换并持久化 -> `test_app_toggles_and_persists_theme`
- [ ] 首屏在挂载前设置主题，避免闪烁 -> `test_index_applies_theme_before_mount`
- [ ] 样式表没有写死的浅色值 -> `test_styles_use_tokens_only`
- [ ] 构建产物包含主题切换 -> `test_dark_theme_is_built`
- [ ] 手册设置一节说明主题 -> `test_guide_documents_dark_theme`
- [ ] `--full` 门禁通过

## 反例

master 上 `tokens.css` 只有 `:root` 浅色值，`index.html` 无主题脚本，顶栏无切换按钮，
`style.css` 有写死的 `#fecdca`；上述用例失败。

## 5 问威胁建模

1. **数据**：只存一个 `light|dark` 偏好，无个人信息。
2. **调用方**：纯前端，不需要登录即可在登录页切换。
3. **信任边界**：`localStorage` 值只用于选择两套内建主题，非法值回落到系统偏好。
4. **恶意输入**：内联脚本对读取值做白名单判断，不把值拼进 HTML。
5. **失败是否泄露信息**：无网络请求、无日志。

## 范围外

- 每个视图的自定义配色（全部走 token）。
- 高对比度/色弱模式。
- 旧版（legacy）内联界面。

## 证据

- `docs/evidence/SLICE-302-dark-theme.txt`
- `docs/evidence/ui/SLICE-302-dark.png`
- `docs/evidence/ui/SLICE-302-dark-phone.png`
