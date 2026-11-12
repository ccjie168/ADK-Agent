# SLICE-042 MCP HTTP OIDC 认证

状态: gated
依据: ADR-0002 第 7 条，ADR-0007

## 意图（要什么，不写怎么写）

给 `adk-agent serve` 和 `serve-many` 的 `streamable-http` 传输加 OIDC 鉴权。这一刀只做认证，不把 principal 注入 agent 运行。

- 两个命令都加 `--oidc-config FILE`。给了就复用 `OidcAuthMiddleware`，忽略 `--auth-token-env`，允许绑定非回环地址。
- 只对 `streamable-http` 生效。stdio 传输同时给 `--oidc-config` 退出 1，因为没有 HTTP 请求可鉴权。
- `--oidc-config` 和 `--allow-unauthenticated` 互斥。
- 没有 token 或 token 不合法返回 401 `unauthorized`。签发方不可达返回 503 `identity_unavailable`。
- `/healthz` 保持开放。
- 静态 token 模式和 stdio 行为不变。

实验已经确认，MCP 工具可以通过 `ctx.request_context.request.state` 读到中间件挂的 principal。principal 注入单独排在 SLICE-043，因为要替换 ADK 的 `_run_agent` 用户 id 和会话归属。

## 新增文件

- `tests/test_mcp_oidc.py`
- `docs/evidence/SLICE-042-mcp-http-oidc.txt`

## 修改文件

- `src/adk_agent/mcp/http.py`：`build_http_app` 和 `run_http` 的 `oidc` 参数与中间件
- `src/adk_agent/mcp/server.py`：`serve_agent` 和 `serve_many` 透传 `oidc`
- `src/adk_agent/cli.py`：两个命令的 `--oidc-config`、stdio 检查
- `docs/contracts/cli.md`：MCP HTTP 鉴权说明
- `docs/specs/ROADMAP.md`

## 完成判据（可执行）

- [x] OIDC 模式下 `/healthz` 开放 -> `tests/test_mcp_oidc.py::test_healthz_open`
- [x] 缺 token 返回 401 -> `tests/test_mcp_oidc.py::test_missing_token_is_401`
- [x] 非法 token 返回 401 -> `tests/test_mcp_oidc.py::test_invalid_token_is_401`
- [x] 签发方不可达返回 503 -> `tests/test_mcp_oidc.py::test_provider_outage_is_503`
- [x] 合法 token 放行到 MCP 应用 -> `tests/test_mcp_oidc.py::test_valid_token_reaches_mcp_app`
- [x] `serve` 把 `oidc` 传给 `serve_agent` -> `tests/test_mcp_oidc.py::test_cli_serve_passes_oidc`
- [x] `serve-many` 把 `oidc` 传给 `serve_many` -> `tests/test_mcp_oidc.py::test_cli_serve_many_passes_oidc`
- [x] stdio 加 `--oidc-config` 退出 1 -> `tests/test_mcp_oidc.py::test_cli_rejects_oidc_on_stdio`
- [x] 配置和 `--allow-unauthenticated` 互斥 -> `tests/test_mcp_oidc.py::test_cli_rejects_oidc_with_unauthenticated`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`build_http_app(server, oidc=provider)` -> 当前 `TypeError`
- [x] 反例 2：`serve --oidc-config FILE --transport streamable-http` -> 当前 argparse 退出 2
- [x] 反例 3：`serve --oidc-config FILE` 用 stdio -> 期望退出 1
- [x] 反例 4：JWKS 不可达 -> 期望 503 `identity_unavailable`

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`，再改代码。

- `serve` 和 `serve-many` 的 `streamable-http` 支持 `--oidc-config FILE`。
- stdio 加该参数退出 1。
- 与 `--allow-unauthenticated` 互斥。
- 401 `unauthorized`，503 `identity_unavailable`。
- 这一版 agent 运行仍使用 ADK 的 `mcp_user`，没有 principal 注入。

## 5 问威胁建模（10 分钟）

1. **数据**：MCP 请求、JWT、请求主体。
2. **调用方**：MCP host，例如 Claude Code 或 IDE。
3. **信任边界**：host 到 MCP HTTP 服务，issuer 的 JWKS 到服务。
4. **恶意输入最坏结果**：伪造 token 就能调用 agent 工具。缓解在解析器，只收非对称签名并校验 issuer、audience、exp、kid。这一刀不注入 principal，所以 agent 运行归属仍是 ADK 的 `mcp_user`，审计归属不完整。这个缺口明确留给 SLICE-043。
5. **失败是否泄露信息**：401 和 503 只返回固定代码，不带 token、claims 或 JWKS 地址。

## 范围外

- principal 注入 agent 运行和按用户会话归属，排在 SLICE-043。
- A2A 的 per-peer 身份，维持 ADR-0003。
- stdio 鉴权，没有传输层身份可用。
- MCP 路径的工具守卫和模型网关接入，属于已有缺口，不在这一刀。

## 证据

- 反例红: `docs/evidence/SLICE-042-mcp-http-oidc.txt`，9 个用例失败，缺少 `oidc=` 和 `--oidc-config`
- 实现后绿: 同文件，9 个目标测试通过，全量 450 passed 2 skipped，`check.py --full` ALL PASS，另做真实 MCP 客户端验证
