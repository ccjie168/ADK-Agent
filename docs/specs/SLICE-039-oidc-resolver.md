# SLICE-039 OIDC 身份解析器核心

状态: gated
依据: ADR-0002 第 7 条，ADR-0007

## 意图（要什么，不写怎么写）

实现 `core.ports.IdentityProvider` 的第一个真实适配器，把一张 OIDC 的 JWT 验证成 `Principal`。这一刀只做解析器，不接 HTTP 面，也不改启动参数。

- 配置是类型化模型。`issuer`、`audience`、`jwks_url` 必填。算法只收非对称，默认 `RS256` 和 `ES256`。时钟偏差默认 60 秒。租户、角色、kind 的 claim 名可配置，默认 `tenant`、`roles`、`kind`。
- 验证签名、`iss`、`aud`、`exp`，`iat` 必须存在，`nbf` 存在时校验。`kid` 缺失拒绝。
- JWKS 默认用 PyJWT 的 `PyJWKClient`，缓存寿命 300 秒。允许注入 key resolver，测试不联网。
- claims 映射到 `Principal`。`sub` 到 `subject`，租户 claim 缺失拒绝，角色缺失记空列表，kind 缺失记 `human`。
- 失败分两类。token 不合法抛 `InvalidIdentity`，依赖缺失或 JWKS 取不到抛 `IdentityUnavailable`。两者都不带 token 内容和 key 材料。
- 配置在构造时拒绝非法状态。HMAC、`none`、空算法列表、非回环的明文 JWKS URL 都构造失败。

这一刀不做 HTTP 接线、JSON 配置文件、多 issuer、introspection 和撤销列表。

## 新增文件

- `src/adk_agent/identity/__init__.py`
- `src/adk_agent/identity/oidc.py`
- `tests/identity/test_oidc_config.py`
- `tests/identity/test_oidc_provider.py`
- `docs/evidence/SLICE-039-oidc-resolver.txt`

## 修改文件

- `docs/specs/ROADMAP.md`：登记 SLICE-039

## 数据形状

```python
class OidcConfig(BaseModel):
    issuer: str
    audience: str
    jwks_url: str
    algorithms: tuple[str, ...] = ("RS256", "ES256")
    leeway_seconds: int = 60
    tenant_claim: str = "tenant"
    roles_claim: str = "roles"
    kind_claim: str = "kind"

class OidcIdentityProvider:
    def __init__(self, config: OidcConfig, *, key_resolver: Callable[[str], Any] | None = None): ...
    async def resolve(self, credential: str) -> Principal: ...
```

`resolve` 返回 `Principal`。异常层次是 `IdentityError` 下的 `InvalidIdentity` 和 `IdentityUnavailable`。

## 完成判据（可执行）

- [x] 合法 token 解析出 `Principal` -> `tests/identity/test_oidc_provider.py::test_valid_token_maps_to_principal`
- [x] 缺失租户 claim 拒绝 -> `tests/identity/test_oidc_provider.py::test_missing_tenant_is_rejected`
- [x] 角色缺失记空列表 -> `tests/identity/test_oidc_provider.py::test_missing_roles_defaults_to_empty`
- [x] kind 缺失记 `human`，非法 kind 拒绝 -> `tests/identity/test_oidc_provider.py::test_kind_mapping`
- [x] 签发者不匹配拒绝 -> `tests/identity/test_oidc_provider.py::test_wrong_issuer_is_rejected`
- [x] 受众不匹配拒绝 -> `tests/identity/test_oidc_provider.py::test_wrong_audience_is_rejected`
- [x] 过期 token 拒绝 -> `tests/identity/test_oidc_provider.py::test_expired_token_is_rejected`
- [x] 缺失 `exp` 拒绝 -> `tests/identity/test_oidc_provider.py::test_missing_exp_is_rejected`
- [x] 缺失 `iat` 拒绝 -> `tests/identity/test_oidc_provider.py::test_missing_iat_is_rejected`
- [x] 默认 `PyJWKClient` 路径取键 -> `tests/identity/test_oidc_provider.py::test_default_resolver_uses_jwk_client`
- [x] 签名被篡改拒绝 -> `tests/identity/test_oidc_provider.py::test_tampered_signature_is_rejected`
- [x] 不在白名单的算法拒绝 -> `tests/identity/test_oidc_provider.py::test_disallowed_algorithm_is_rejected`
- [x] 缺 `kid` 拒绝 -> `tests/identity/test_oidc_provider.py::test_missing_kid_is_rejected`
- [x] key resolver 失败抛 `IdentityUnavailable` -> `tests/identity/test_oidc_provider.py::test_key_resolution_failure_is_unavailable`
- [x] 配置拒绝 HMAC 和 `none` -> `tests/identity/test_oidc_config.py::test_config_rejects_symmetric_and_none`
- [x] 配置拒绝空算法列表 -> `tests/identity/test_oidc_config.py::test_config_rejects_empty_algorithms`
- [x] 非回环明文 JWKS URL 拒绝 -> `tests/identity/test_oidc_config.py::test_config_requires_tls_outside_loopback`
- [x] 回环明文 JWKS URL 允许 -> `tests/identity/test_oidc_config.py::test_config_allows_loopback_http`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.identity import OidcIdentityProvider` -> 当前 `ImportError`
- [x] 反例 2：`OidcConfig(algorithms=("HS256",), ...)` -> 当前 `ImportError`
- [x] 反例 3：过期 token 被接受 -> 期望 `InvalidIdentity`
- [x] 反例 4：受众错误的 token 被接受 -> 期望 `InvalidIdentity`
- [x] 反例 5：缺租户 claim 的 token 被接受 -> 期望 `InvalidIdentity`
- [x] 反例 6：JWKS 取不到时降级放行 -> 期望 `IdentityUnavailable`

## 契约（如涉及对外接口）

本切片不新增对外 HTTP 接口，也不改 CLI。`OidcConfig` 的 JSON schema 和 HTTP 接线在 SLICE-040 里先写契约。

## 5 问威胁建模（10 分钟）

1. **数据**：OIDC 签发的 JWT，其中的 `sub`、租户、角色、kind，以及映射出的 `Principal`。
2. **调用方**：未来的 HTTP 鉴权中间件和 A2A 消费方，都在 SLICE-040 接线。
3. **信任边界**：客户端送来的 token 不可信。issuer 的 JWKS 是外部网络资源。配置来自运维。
4. **恶意输入最坏结果**：接受无签名、HMAC 或 `none` 的 token，攻击者可以伪造任意主体。缓解是算法只收非对称白名单，强制 `exp`、`iat` 和 `kid`，校验签发者与受众，签名验证失败即拒绝。恶意 `kid` 只影响 key 选择，不拼文件路径。JWKS URL 在非回环时必须用 TLS，避免中间人替换公钥。
5. **失败是否泄露信息**：异常只带固定原因码，不带 token、claim 原文或公钥。`IdentityUnavailable` 只说明依赖缺失或 JWKS 不可达。

## 证据

- 反例红: `docs/evidence/SLICE-039-oidc-resolver.txt`，`adk_agent.identity` 不存在，2 个测试文件收集失败
- 实现后绿: 同文件，18 个身份测试通过，全量 410 passed 2 skipped，`check.py --full` ALL PASS，另做真实 JWKS 取键验证
