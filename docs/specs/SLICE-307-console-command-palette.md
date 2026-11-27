# SLICE-307 控制台命令面板

状态: active
依据: `docs/PROGRESS.md` 第 16 节「命令面板仍未做」（ADR-0041 视觉改造的最后一项）

## 意图

27 个控制台面板靠侧边栏逐级点击。加一个命令面板：

1. `Ctrl+K`（macOS `⌘K`）打开，输入即过滤，`↑`/`↓` 选择，`Enter` 跳转，`Esc` 关闭。
2. 只列出调用方有能力的入口，与侧边栏同一份数据；外部链接（使用说明）不进面板。
3. 面板的数据源 `web/src/nav.ts` 与侧边栏逐条对齐，由用例守卫两边路由集合相等；
   本次不改写侧边栏渲染（现有用例锁定了它的写法）。

## 契约（先改）

`docs/guides/console-ui.html`：在「快速开始与登录」之后新增「键盘与命令面板」一节，
写明快捷键、过滤与选择键、只显示有能力的入口。

对外 HTTP 接口不变；这是纯前端改动，新增文件：

- `web/src/nav.ts`：`NAV_GROUPS`（分组 → 子分组 → 条目，条目含 `to`、`label`、`icon`、
  可选 `capability`、可选 `external`），组可见性由「组内至少一个条目可见」决定。
- `web/src/components/CommandPalette.vue`：`open` 属性 + `close` 事件；`role="dialog"`、
  `aria-modal="true"`、输入框 `aria-label`、`aria-activedescendant`。

## 完成判据

- [ ] `nav.ts` 的路由都在 router、能力都在 `capabilities.ts`，且与侧边栏路由集合相等 -> `test_nav_source_is_shared`
- [ ] 面板按能力过滤，无能力的入口不出现 -> `test_palette_filters_by_capability`
- [ ] 对话框角色、键盘选择与焦点管理 -> `test_palette_keyboard_and_a11y`
- [ ] `Ctrl+K` / `⌘K` 打开，`Esc` 关闭 -> `test_palette_shortcut_is_wired`
- [ ] `web/dist` 重建后包含面板标记 -> `test_palette_is_built`
- [ ] 使用说明记录快捷键 -> `test_guide_documents_the_palette`
- [ ] `--full` 门禁通过

## 反例

master 上没有 `web/src/nav.ts` 与 `CommandPalette.vue`，侧边栏链接是 `App.vue` 里的
手写列表；以上用例全部失败。

## 5 问威胁建模

1. **数据**：只有路由名与标签，没有业务数据。
2. **调用方**：已登录的控制台用户；面板不新增请求，只做 `router.push`。
3. **信任边界**：能力判断仍在浏览器与服务端两处；面板隐藏不等于授权，服务端不变。
4. **恶意输入**：查询串只做本地字符串匹配，不拼 HTML（无 `v-html`）。
5. **失败是否泄露信息**：不显示调用方没有能力的入口名称。

## 范围外

- Agent、运行、审批等对象的模糊搜索结果（需要新查询接口）。
- 移动端手势；`Ctrl+K` 在触屏上不适用，侧边栏保持原样。

## 证据

- `docs/evidence/SLICE-307-command-palette.txt`
