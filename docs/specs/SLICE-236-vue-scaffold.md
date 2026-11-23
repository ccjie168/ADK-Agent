# SLICE-236 Vue 前端脚手架 + FastAPI 挂载

状态: gated
依据: ADR-0041 阶段 0 第一步（Vue 地基）

## 意图

1. 建 `web/` 前端目录：Vue 3 + Vite + TypeScript 的最小可构建 shell（一个顶栏 + 占位侧栏 + 明确标记
   文案「ADK Console · Vue」），不引入 Vue Router / Pinia（后续切面板时再加）。
2. `npm install` 产出 `package-lock.json`，`npm run build` 产出 `web/dist/`（本切片提交产物，让 FastAPI
   无需构建即可服务）。
3. 控制台加 `--ui {legacy,vue}`（默认 `legacy`）：`vue` 时 FastAPI 在 `/` 服务 `dist/index.html`、在
   `/assets` 挂 `dist/assets`；`legacy` 维持现有内联 `_INDEX_HTML`。`/api/*` 路由两种模式都照常。
4. `.gitignore` 加 `node_modules/`。

## 契约（先改）

- `docs/contracts/console.md`：补 `--ui legacy|vue` 开关与两种渲染来源的说明。

## 完成判据

- [ ] `--ui vue` 时 `/` 返回 200 且含 Vue 标记 -> `test_vue_shell_served`
- [ ] `--ui legacy`（默认）`/` 仍返回内联壳 -> `test_legacy_shell_default`
- [ ] `/assets/` 下产物可访问 -> `test_vue_assets_served`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

- 基线（无 `web/`、无 `--ui`）：`console --ui vue` 报未知参数；`/` 只有内联壳，无 Vue 标记。加用例、
  未改实现时失败。

## 5 问威胁建模

1. **数据**：静态前端产物，无敏感信息。
2. **调用方**：浏览器；鉴权仍在 `/api/*` 层，`/` 与 `/assets` 是公开壳。
3. **信任边界**：SPA 只做渲染，能力判定仍由 `/api/*` 服务端强制（前端隐藏不等于授权）。
4. **恶意输入最坏结果**：静态文件路径穿越。缓解：`StaticFiles` 只挂白名单目录，不接用户输入路径。
5. **失败是否泄露信息**：不泄露。

## 范围外

- 面板迁移（后续切片）、Vue Router / Pinia、前端 lint/audit 接入门禁。

## 证据

- `docs/evidence/SLICE-236-vue-scaffold.txt`
