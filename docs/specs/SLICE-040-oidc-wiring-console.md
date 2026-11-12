# SLICE-040 OIDC 接线：控制台与中间件

状态: in_progress
依据: ADR-0002 第 7 条，ADR-0007，SLICE-039

## 意图（要什么，不写怎么写）

把 SLICE-039 的解析器接到控制台。这一刀只做控制台和通用中间件，模型网关、工具网关、审计服务和 MCP HTTP 留在 SLICE-041。

- 新增 `OidcAuthMiddleware`。它从 `Authorization: Bearer` 取 token，调用 `IdentityProvider.resolve`，把 `Principal` 挂到 `request.state.principal`。token 不合法返回 401 `unauthorized`，签发方不可达返回 503 `identity_unavailable`。
- `console --oidc-config FILE` 切换到 OIDC 模式。配置是 `OidcConfig` JSON，契约见 `oidc_config.schema.json`。
- 控制台的 RBAC、审计事件和会话都改用请求里的 principal，不再用启动参数里的单一身份。
- 会话按 principal 的 `subject` 隔离。两个用户不会看到彼此的会话。
- 非 `admin` 身份只能读自己租户的注册表。admin 可以跨租户读。
- 策略更新仍由 `policy.update` 的 RBAC 判定，角色来自 token。没有单独的管理员硬检查。
- 静态 token 模式和 `--allow-unauthenticated` 开发模式不变。OIDC 模式跳过静态 token 检查，因此允许绑定非回环地址。
- `--oidc-config` 和 `--allow-unauthenticated` 互斥。

这一刀不做服务面接线、OIDC discovery、introspection、撤销列表和多 issuer。

## 新增文件

- `tests/test_oidc_auth.py`
- `tests/test_console_oidc.py`
- `docs/evidence/SLICE-040-oidc-wiring-console.txt`

## 修改文件

- `src/adk_agent/auth.py`：新增 `OidcAuthMiddleware`
- `src/adk_agent/cli.py`：`console --oidc-config`、配置加载、互斥检查
- `src/adk_agent/console.py`：OIDC 参数、请求 principal、按 subject 的会话、注册表租户检查
- `scripts/export_contracts.py`：导出 `OidcConfig`
- `docs/contracts/oidc_config.schema.json`（新）
- `docs/contracts/cli.md`、`docs/contracts/console.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`

## 数据形状

- `OidcConfig` 沿用 SLICE-039 的模型。
- 请求 principal 存在 `request.state.principal`，类型是 `Principal`。
- CLI 参数 `--oidc-config FILE`。
- 静态模式的本地 principal 保留为回退值，OIDC 模式不读它的租户、角色和 subject。

## 完成判据（可执行）

- [ ] 合法 token 把 principal 挂到请求上 -> `tests/test_oidc_auth.py::test_valid_token_sets_request_principal`
- [ ] 缺 header 返回 401 -> `tests/test_oidc_auth.py::test_missing_header_is_401`
- [ ] 非法 token 返回 401 -> `tests/test_oidc_auth.py::test_invalid_token_is_401`
- [ ] 签发方不可达返回 503 -> `tests/test_oidc_auth.py::test_provider_unavailable_is_503`
- [ ] 开放路径不鉴权 -> `tests/test_oidc_auth.py::test_open_path_skips_auth`
- [ ] 控制台 OIDC 模式放行合法 token -> `tests/test_console_oidc.py::test_console_accepts_oidc_token`
- [ ] 控制台 OIDC 模式拒绝无 token -> `tests/test_console_oidc.py::test_console_rejects_missing_token`
- [ ] 控制台 OIDC 模式把签发方不可达映射为 503 -> `tests/test_console_oidc.py::test_console_maps_provider_outage_to_503`
- [ ] 会话按 subject 隔离 -> `tests/test_console_oidc.py::test_sessions_are_scoped_by_subject`
- [ ] 非 admin 不能跨租户读注册表 -> `tests/test_console_oidc.py::test_registry_tenant_is_enforced`
- [ ] admin 可以跨租户读注册表 -> `tests/test_console_oidc.py::test_registry_admin_can_cross_tenants`
- [ ] 策略更新使用 token 角色 -> `tests/test_console_oidc.py::test_policy_update_uses_token_roles`
- [ ] `console --oidc-config` 可解析 -> `tests/test_console_oidc.py::test_cli_accepts_oidc_config`
- [ ] 配置文件和 `--allow-unauthenticated` 互斥 -> `tests/test_console_oidc.py::test_cli_rejects_oidc_with_unauthenticated`
- [ ] 配置文件缺失退出 1 -> `tests/test_console_oidc.py::test_cli_rejects_missing_config`
- [ ] 契约与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.auth import OidcAuthMiddleware` -> 当前 `ImportError`
- [ ] 反例 2：`adk-agent console --oidc-config FILE` -> 当前 argparse 退出 2
- [ ] 反例 3：非 admin 身份读别的租户 -> 当前静态模式放行，期望 403 `tenant_forbidden`
- [ ] 反例 4：两个 subject 看到彼此的会话 -> 当前都用 `console_user`，期望只看到自己的
- [ ] 反例 5：没有 `policy.update` 角色的 token 改策略 -> 当前用本地 admin 角色放行，期望 403 `policy_denied`
- [ ] 反例 6：JWKS 不可达时放行 -> 期望 503 `identity_unavailable`

## 契约（如涉及对外接口）

先改契约，再改代码。

- `docs/contracts/oidc_config.schema.json` 由 `scripts/export_contracts.py` 从 `OidcConfig` 生成。
- `console.md` 写明两种鉴权模式、401 与 503、按 subject 的会话、注册表租户规则。
- `cli.md` 写明 `--oidc-config`、互斥规则和失败退出码。

## 5 问威胁建模（10 分钟）

1. **数据**：JWT，principal 的租户、subject、角色和 kind，会话，审计事件，访问策略。
2. **调用方**：持有 OIDC token 的控制台运维。
3. **信任边界**：浏览器到控制台，issuer 的 JWKS 到控制台，控制台到会话存储和注册表文件。
4. **恶意输入最坏结果**：伪造 token 可以冒充任意主体。缓解在解析器，只收非对称签名并校验 issuer、audience、exp、kid。跨租户读注册表会泄露别人的 agent 元数据，按 principal 租户和 admin 角色拦截。共享会话会泄露对话，按 subject 隔离。策略抬权由 `policy.update` 的 RBAC 按 token 角色判定。
5. **失败是否泄露信息**：错误只返回固定代码。401 和 503 不带 token、claims 或 JWKS 地址。

## 范围外

- 模型网关、工具网关、审计服务和 MCP HTTP 的 OIDC 接线，排在 SLICE-041。
- MCP 每次调用的 principal 注入。ADK 的 MCP runner 自己建 invocation，需要单独设计。
- OIDC discovery、introspection、撤销列表、多 issuer。
- 细粒度的 `registry.read` 策略动作。当前规则是 admin 或同租户。

## 证据

- 反例红: 待补
- 实现后绿: 待补
