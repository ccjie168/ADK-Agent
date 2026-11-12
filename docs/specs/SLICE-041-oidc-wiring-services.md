# SLICE-041 OIDC 接线：服务面

状态: gated
依据: ADR-0002 第 7 条，ADR-0007，SLICE-039、SLICE-040

## 意图（要什么，不写怎么写）

把 OIDC 接到三个独立服务：模型网关、工具网关和审计服务。MCP HTTP 和 A2A 不在这一刀。

- 三个 `serve-*` 命令都加 `--oidc-config FILE`。给了就复用 `OidcAuthMiddleware`，忽略 `--auth-token-env`，并且不能和 `--allow-unauthenticated` 同时给。
- 中间件验证 token 后把 `Principal` 挂到请求上。服务把它当成唯一可信身份。
- 请求体里的 principal 只用于对齐。`tenant` 和 `subject` 必须和 token 一致，否则返回 403 `principal_mismatch`。
- 对齐后，角色的来源是 token，不是请求体。模型网关和工具网关的审计事件、审计服务的记录都用 token 里的 `roles`、`kind`、`attributes`。
- 没有 token 或 token 不合法返回 401 `unauthorized`。签发方不可达返回 503 `identity_unavailable`。
- 静态 token 模式完全不变。

这一刀不改调用方送来的 `policy` 和 `grants`。按 ADR-0004，per-caller 策略权威是后续工作。

## 新增文件

- `tests/test_service_oidc.py`
- `docs/evidence/SLICE-041-oidc-wiring-services.txt`

## 修改文件

- `src/adk_agent/auth.py`：新增 `bind_principal`，校验 tenant 和 subject 并返回 token principal
- `src/adk_agent/models/service.py`：`oidc` 参数、中间件、principal 绑定
- `src/adk_agent/tools/service.py`：同上
- `src/adk_agent/audit/service.py`：同上
- `src/adk_agent/cli.py`：三个命令的 `--oidc-config`，`_identity_provider` 统一做互斥和报错
- `docs/contracts/cli.md`：三个命令的 OIDC 参数和 `principal_mismatch`
- `docs/specs/ROADMAP.md`

## 数据形状

- token principal 来自 `OidcIdentityProvider.resolve`。
- 绑定规则：`claimed.tenant == verified.tenant` 且 `claimed.subject == verified.subject`。通过后用 `verified` 替换请求体里的 principal，其余字段不动。
- 事件用 `AuditEvent.model_copy(update={"principal": verified})`。

## 完成判据（可执行）

- [x] 模型网关缺 token 返回 401 -> `tests/test_service_oidc.py::test_model_gateway_requires_token`
- [x] 模型网关 tenant 不匹配返回 403 -> `tests/test_service_oidc.py::test_model_gateway_rejects_principal_mismatch`
- [x] 模型网关用 token 角色覆盖请求体角色 -> `tests/test_service_oidc.py::test_model_gateway_uses_token_principal`
- [x] 工具网关缺 token 返回 401 -> `tests/test_service_oidc.py::test_tool_gateway_requires_token`
- [x] 工具网关 tenant 不匹配返回 403 -> `tests/test_service_oidc.py::test_tool_gateway_rejects_principal_mismatch`
- [x] 工具网关用 token 角色覆盖请求体角色 -> `tests/test_service_oidc.py::test_tool_gateway_uses_token_principal`
- [x] 审计服务缺 token 返回 401 -> `tests/test_service_oidc.py::test_audit_service_requires_token`
- [x] 审计服务 tenant 不匹配返回 403 -> `tests/test_service_oidc.py::test_audit_service_rejects_principal_mismatch`
- [x] 审计服务用 token 角色覆盖事件角色 -> `tests/test_service_oidc.py::test_audit_service_uses_token_principal`
- [x] 签发方不可达返回 503 -> `tests/test_service_oidc.py::test_service_maps_provider_outage_to_503`
- [x] `serve-audit --oidc-config` 可解析 -> `tests/test_service_oidc.py::test_cli_accepts_oidc_config`
- [x] 配置和 `--allow-unauthenticated` 互斥 -> `tests/test_service_oidc.py::test_cli_rejects_oidc_with_unauthenticated`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`serve-model-gateway --oidc-config FILE` -> 当前 argparse 退出 2
- [x] 反例 2：请求体 principal 的 tenant 和 token 不一致 -> 当前被接受，期望 403 `principal_mismatch`
- [x] 反例 3：请求体 principal 自带 `admin` 角色，token 没有 -> 当前审计按 `admin` 记录，期望按 token 的角色记录
- [x] 反例 4：JWKS 不可达 -> 期望 503 `identity_unavailable`

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`，再改代码。

- 三个命令加 `--oidc-config FILE`。
- 与 `--allow-unauthenticated` 互斥。
- 请求体 principal 的 `tenant` 和 `subject` 必须与 token 一致，否则 403 `principal_mismatch`。
- 角色、kind、attributes 以 token 为准。

## 5 问威胁建模（10 分钟）

1. **数据**：模型调用、工具调用、审计事件、principal 和 JWT。
2. **调用方**：运行时 worker 和上游网关。
3. **信任边界**：调用方到服务的 HTTP，issuer 的 JWKS 到服务。
4. **恶意输入最坏结果**：持有合法 token 的调用方在请求体里冒充别的租户或主体，或者伪造 `admin` 角色来污染审计和策略判定。缓解是 tenant 和 subject 必须与 token 一致，角色以 token 为准。被盗 token 仍是有效身份，控制手段是短有效期和 JWKS 轮换。
5. **失败是否泄露信息**：401、403、503 只返回固定代码，不带 token、claims 或 JWKS 地址。

## 范围外

- MCP HTTP 的 OIDC 接线和每次调用的 principal 注入，排在 SLICE-042。
- A2A 的 per-peer 身份，维持 ADR-0003 的共享 token。
- 按 token 角色推导 `policy` 和 `grants`。当前仍信任调用方送来的策略，依据 ADR-0004。
- OIDC discovery、introspection、撤销列表、多 issuer。

## 证据

- 反例红: `docs/evidence/SLICE-041-oidc-wiring-services.txt`，14 个用例失败，服务缺 `oidc=`，CLI 不认 `--oidc-config`
- 实现后绿: 同文件，14 个目标测试通过，全量 441 passed 2 skipped，`check.py --full` ALL PASS，另做真实 JWKS 双服务验证
