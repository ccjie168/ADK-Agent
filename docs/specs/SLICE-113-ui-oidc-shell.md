# SLICE-113 控制台 OIDC 登录与应用外壳

状态: gated
依据: 调研记录 `docs/research/agent-framework-landscape.md` 的 UI 参考；身份验证沿用 ADR-0007，浏览器登录不加新依赖。

## 意图（要什么，不写怎么写）

控制台从单页工具升级为可分发的应用外壳。用户通过组织身份登录，不再把共享 Bearer token 复制进浏览器；开发环境仍保留手工 token 入口。界面按运营、构建、治理分组，支持深色主题、可分享的标签地址与窄屏布局。

- 配置文件有 `browser` 段时，登录页显示“使用 OIDC 登录”，走授权码加 PKCE（S256）。
- 浏览器只拿公开参数；`token_endpoint` 与 `client_secret_env` 留在服务端，token 兑换由控制台代发。
- 回调地址必须与配置一致；state 不匹配时拒绝登录并给出固定文案。
- 没有 `browser` 段时保持手工 Bearer token 登录，`/auth/config` 返回 `{"enabled": false}`。
- 登录后显示应用外壳：顶栏放 agent、租户、连接状态、主题与退出；左侧分组导航放十一个面板；`#tab` 可直达面板。
- 主题选择存 `localStorage`，token 只存当前标签页的 `sessionStorage`。
- 窄屏（宽度不大于 760px）下导航变成顶部换行布局，不出现横向滚动。

## 新增文件

- `src/adk_agent/identity/oidc_login.py`
- `tests/test_oidc_login.py`
- `tests/test_console_oidc_login.py`
- `docs/evidence/SLICE-113-ui-oidc-shell.txt`

## 修改文件

- `src/adk_agent/identity/oidc.py`（`OidcBrowserConfig` 与 `OidcConfig.browser`）
- `src/adk_agent/identity/__init__.py`（导出）
- `src/adk_agent/console.py`（登录卡片、应用外壳、`/auth/*` 三个端点）
- `src/adk_agent/cli.py`（控制台把 `browser` 段接成 `OidcLogin`）
- `docs/contracts/console.md`（`/auth/*` 契约）
- `docs/contracts/oidc_config.schema.json`（重新导出）
- `docs/guides/operations.md`（浏览器登录配置示例）

## 完成判据（可执行）

- [x] 有浏览器配置时 `/auth/config` 返回公开参数，且不含 `token_endpoint` 与 `client_secret_env` -> `tests/test_oidc_login.py::test_public_config_hides_server_settings` / `tests/test_console_oidc_login.py::test_auth_config_with_oidc`
- [x] 兑换请求带 `grant_type=authorization_code`、code 与 verifier -> `tests/test_oidc_login.py::test_exchange_posts_the_authorization_code`
- [x] `redirect_uri` 与配置不一致时拒绝 -> `::test_redirect_uri_must_match`
- [x] verifier 长度不合规时拒绝 -> `::test_short_verifier_is_rejected`
- [x] 上游非 200 或缺 token 时拒绝 -> `::test_non_200_is_an_error` / `::test_missing_access_token_is_an_error`
- [x] 机密客户端的 secret 只从环境变量读取，缺失即失败 -> `::test_confidential_client_secret_comes_from_env` / `::test_missing_client_secret_fails`
- [x] 回环地址外使用明文 HTTP 的配置被拒绝 -> `::test_browser_config_rejects_plain_http_outside_loopback`
- [x] `/auth/token` 校验请求体、映射兑换失败为 401、无配置返回 404 -> `tests/test_console_oidc_login.py::test_auth_token_rejects_invalid_body` / `::test_auth_token_maps_exchange_errors_to_401`
- [x] `/auth/callback` 返回控制台 HTML -> `::test_auth_callback_serves_the_app`
- [x] 浏览器完整走通授权码加 PKCE，回调后进入外壳并加载数据 -> 证据文件中的 mock IdP 流程：`GET /authorize` 302、`POST /token` 200、`GET /api/agents` 200
- [x] state 不匹配与退出登录行为正确 -> 证据文件：回调显示固定文案；退出后 token 清空并回到登录页

## 反例（必须在实现前跑红）

- [x] 反例 1：不校验回调地址，攻击者用别的 `redirect_uri` 兑换 code -> 期望 `::test_redirect_uri_must_match` 失败
- [x] 反例 2：把 `token_endpoint` 或 secret 环境变量名下发给浏览器 -> 期望 `::test_public_config_hides_server_settings` 失败
- [x] 反例 3：上游失败仍返回 200 或空 token -> 期望 `::test_non_200_is_an_error` 与 `::test_missing_access_token_is_an_error` 失败
- [x] 反例 4：缺字段的 `/auth/token` 请求被接受 -> 期望 `::test_auth_token_rejects_invalid_body` 失败
- [x] 反例 5：state 不匹配仍完成登录 -> 期望浏览器证据中的回调显示“登录状态不匹配，请重试”

## 契约（如涉及对外接口）

`docs/contracts/console.md` 增加 `/auth/config`、`/auth/callback`、`/auth/token` 的形状与错误码。`OidcConfig` 的 `browser` 段进 `docs/contracts/oidc_config.schema.json`。先改契约与 schema，再改代码。

## 5 问威胁建模（10 分钟）

1. **数据**：授权码、PKCE verifier、access token、客户端 secret、用户与租户声明。
2. **调用方**：浏览器、控制台服务端、IdP token endpoint。
3. **信任边界**：浏览器到控制台；控制台到 IdP；token 到 `/api/*` 的 bearer 校验。
4. **恶意输入最坏结果**：伪造回调地址偷 code（缓解：服务端比对 `redirect_uri`）；注入脚本偷 token（缓解：token 只在 `sessionStorage`，页面不拼接用户输入）；state 固定导致 CSRF（缓解：每次登录随机 state 并校验）；secret 泄露到浏览器（缓解：只留在服务端环境变量）；恶意 IdP 返回超大或非 JSON 响应（缓解：固定超时与错误码）。
5. **失败是否泄露信息**：兑换失败统一 401 `oidc_login_failed`，日志只记一条 warning，不回传上游状态或响应体。

## 范围外

- 刷新 token、登出撤销与 IdP 单点登出。
- 角色到界面元素的细粒度隐藏；权限仍由服务端接口判定。
- 运行详情瀑布图、审批工作台与市场卡片改版。另开切片。
- 控制台、MCP、工具网关的护栏接线。

## 证据

- 反例红、实现后绿、浏览器登录与门禁结果: `docs/evidence/SLICE-113-ui-oidc-shell.txt`
