# ADR-0007 OIDC 身份验证用 PyJWT

状态: Proposed   日期: 2026-11-12   签字: 待 Jie CAO 确认

## 背景

ADR-0002 第 7 条把 OIDC 定为默认身份适配器。`IdentityProvider` 端口和 `Principal` 已经在 `core` 里，但现在五个 HTTP 面共用一个 bearer token，RBAC 角色来自启动参数。要做到按调用方授权，先要能从 token 得到可信的 `Principal`。

需要的能力只有四件。验证签发者、受众和有效期，按 `kid` 取公钥，缓存 JWKS，再把 claims 映射到 `Principal`。

2026-11-12 在本机 venv 里核对过三个候选：

- PyJWT 2.15.1 没有必需依赖。`PyJWKClient` 按 `kid` 取公钥并缓存，支持 `lifespan` 和冷却时间。`decode` 直接检查 `issuer`、`audience`、`exp` 和 `leeway`。RSA 和 EC 签名需要 `cryptography`。
- Authlib 1.9.5 依赖 `cryptography` 和 `joserfc`。`authlib.jose` 已标注废弃，而且本版本里 `from authlib.jose import JWT` 直接失败。用它就得改走 `joserfc`，等于多学一层新 API。
- python-jose 本机没装，也没有本项目需要的独有能力。

PyJWT 和 `cryptography` 已经在默认安装里。`mcp` 依赖 PyJWT，`google-adk` 和 `google-auth` 依赖 `cryptography`。所以这一刀不增加实际安装包。

## 决定

1. OIDC 适配器用 PyJWT。依赖写成可选 extra `oidc = ["PyJWT[crypto]>=2,<3"]`，不写进默认依赖。
2. 代码惰性导入 PyJWT。缺依赖时抛 `IdentityUnavailable`，并给出 `pip install "adk-agent[oidc]"`。
3. 只接受非对称签名。默认算法白名单是 `RS256` 和 `ES256`，`none` 和 `HS*` 一律拒绝。
4. 验证必须通过签发者精确匹配，受众包含，`exp` 未过期，`nbf` 和 `iat` 在允许偏差内。偏差默认 60 秒。
5. JWKS 用 `PyJWKClient` 取，缓存寿命默认 300 秒。取不到 JWKS 时抛 `IdentityUnavailable`，不降级为信任未验证的 token。它用标准库取网络，不引入新的 HTTP 客户端。
6. claims 映射固定 `sub` 到 `subject`。租户、角色和 kind 的 claim 名可配置，默认 `tenant`、`roles`、`kind`。租户 claim 缺失即拒绝，不猜默认租户。角色 claim 缺失记为空列表。kind 缺失记 `human`；`client_credentials` 流程的映射排在后续切片。
7. 适配器只返回 `Principal`，不做授权判断。授权仍归 `PolicyEngine`。
8. 这一版不接 introspection、撤销列表、多 issuer 和 ingress 头部信任。头部信任是部署模式，前提是只有 ingress 能访问应用，单独立切片。

## 后果

- 默认安装不变。CI 不装 `oidc` extra 时，OIDC 用例按条件跳过，和 A2A 的处理一致。
- 运行时多一个网络依赖。JWKS 取不到时请求应返回 503，token 不合法时返回 401。这个映射留给接线切片。
- 角色来自 token。启动参数里的单一角色只保留为开发模式。
- 短期没有撤销能力，靠短 token 寿命和 JWKS 轮换。
- 只支持一个 issuer。多 issuer 需要新 ADR 或一次明确的扩展。
