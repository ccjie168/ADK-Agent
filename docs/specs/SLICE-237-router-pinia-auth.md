# SLICE-237 Vue Router + Pinia + SPA 鉴权流

状态: gated
依据: ADR-0041 阶段 0 第二步（Vue 地基：路由、状态与鉴权）

## 意图

在 SLICE-236 的 Vue 脚手架上补三块地基，仍不迁移任何面板（面板逐一切在后续切片做）：

1. 加 `vue-router`（4.x）与 `pinia`（3.x）依赖，`web/src/main.ts` 安装二者。
2. `web/src/router/index.ts`：`createRouter` + `createWebHashHistory`（hash 路由，与 legacy 内联壳一致，
   免后端 catch-all），定义 `/`（总览）与一组面板占位路由，用同一个 `PlaceholderView` 复用；
   `App.vue` 改为 `<RouterView>` 渲染。
3. `web/src/api/client.ts`：`apiFetch(path, init)` 包装 `fetch`，读 `sessionStorage["adk_token"]` 加
   `Authorization: Bearer <token>`，解析 JSON，401 时清 token。
4. `web/src/stores/auth.ts`：Pinia store，状态为 `token` / `principal` / `capabilities` / `oidc`，动作为
   `loadConfig()`（`GET /auth/config`）、`startLogin()`（PKCE，复用 `adk_pkce_verifier`/`adk_pkce_state`）、
   `finishLogin(code, state)`（`POST /auth/token`）、`fetchMe()`（`GET /api/me` 取能力）、`logout()`。
   鉴权语义与 legacy 内联壳一致（token 只存 `sessionStorage`，key `adk_token`）。

后端无改动：`/auth/config`、`/auth/token`、`/api/me`、`/auth/callback` 已存在且已有契约。

## 契约（先改）

无对外接口变化。前端内部结构（Router/Pinia/鉴权 store）是 ADR-0041 已批准的技术栈落地，
`docs/contracts/console.md` 的「前端壳（--ui）」一节无需增补。

## 完成判据

- [ ] `web/package.json` 声明 `vue-router` 与 `pinia` -> `test_package_declares_router_and_pinia`
- [ ] `web/src/main.ts` 安装 router 与 pinia -> `test_main_installs_router_and_pinia`
- [ ] `web/src/router/index.ts` 定义路由 -> `test_router_defines_routes`
- [ ] `web/src/stores/auth.ts` 引用 `/api/me`、`/auth/config`、`/auth/token` 且存 `sessionStorage` -> `test_auth_store_uses_session_token`
- [ ] `web/src/api/client.ts` 加 `Authorization: Bearer` -> `test_api_client_adds_bearer`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-236 状态）：`web/package.json` 无 vue-router/pinia，`web/src/router/`、`web/src/stores/`、
`web/src/api/` 目录不存在，`main.ts` 不安装 router/pinia。五个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：token 只存 `sessionStorage`（标签页级），不落 `localStorage`；PKCE verifier 一次性使用。
2. **调用方**：浏览器；`/api/*` 仍需 Bearer token，401 清 token 回登录，能力判定由服务端强制。
3. **信任边界**：SPA 只做渲染；前端按能力隐藏不等于授权，`/api/*` 各自授权不变。
4. **恶意输入**：PKCE `state` 校验防登录 CSRF，code 与 verifier 只经 `sessionStorage` 一次性消费。
5. **失败是否泄露信息**：登录失败只显示通用文案，不泄露 IdP 端点或 token 细节。

## 范围外

- 面板迁移（后续切片逐个做）、真实面板内容、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-237-router-pinia-auth.txt`
