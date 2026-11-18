# 企业内网的身份认证：AD、Entra ID 与 ADFS

这一页解决“谁可以调用”。凭据密文的密钥放在哪是另一个问题，见 ADR-0026 与
`docs/contracts/credentials.md`。

平台的身份认证只有一条路径：**OIDC**（ADR-0007）。AD、Entra ID（Azure AD）与 ADFS 都通过
OIDC 接入；token 的签名用 JWKS 校验，`tenant`、`roles`、`kind` 从配置的 claim 读取。
不需要绑定 LDAP，也不支持 Kerberos/SPNEGO 或 Windows 集成认证；如果确实要这些，属于新的
identity 适配器，需要单独 ADR。

## 先决条件

- 一个 HTTPS 的 OIDC 签发方（issuer），以及它的 discovery 文档。
- 一个 API 受众（audience）：token 的 `aud` 必须与配置完全一致。
- token 里至少有 `sub`（主体）、租户 claim 与角色 claim。角色是字符串数组，取值
  `admin`、`operator`、`publisher`（也接受 `ops`、`approver`、`developer` 作为别名）。

先从 discovery 文档抄两个值，不要手拼：

```bash
curl -s https://<issuer>/.well-known/openid-configuration
```

- `issuer` 必须与 token 的 `iss` 完全一致（包括结尾斜杠）。
- `jwks_url` 用 discovery 里的 `jwks_uri`。

非回环地址的 `jwks_url` 必须是 HTTPS；回环地址允许 HTTP，便于本地联调。

## 配置格式

配置文件是 `OidcConfig`，字段定义见 `docs/contracts/oidc_config.schema.json`，
`--oidc-config FILE` 在所有服务上通用：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `issuer` | 是 | 与 token 的 `iss` 完全一致 |
| `audience` | 是 | 与 token 的 `aud` 完全一致 |
| `jwks_url` | 是 | discovery 里的 `jwks_uri` |
| `algorithms` | 否 | 默认 `RS256`/`ES256`，只允许非对称算法 |
| `leeway_seconds` | 否 | 时钟偏差容忍，默认 60 |
| `tenant_claim` | 否 | 默认 `tenant` |
| `roles_claim` | 否 | 默认 `roles` |
| `kind_claim` | 否 | 默认 `kind`，缺失按 `human` |
| `browser` | 否 | 控制台浏览器 PKCE 登录，见下文 |

## Entra ID（Azure AD）

单租户应用的典型配置：

```json
{
  "issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
  "audience": "<api-client-id>",
  "jwks_url": "https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys",
  "tenant_claim": "tid",
  "roles_claim": "roles",
  "kind_claim": "kind"
}
```

- `audience` 填接收 token 的那个应用（API）的 client ID；用真实 token 的 `aud` 核对。
- v2 token 的 `iss` 形如上面的 `/v2.0` 结尾；如果签发方仍发 v1 token，`iss` 是
  `https://sts.windows.net/<tenant-id>/`，租户 claim 改用
  `http://schemas.microsoft.com/identity/claims/tenantid`。
- 角色：在应用的“应用角色”里定义 `admin`、`operator`、`publisher`，把用户或组分配上去，
  并确认 token 配置里启用了 `roles` claim。组 claim 可能超长溢出，优先用应用角色。
- `kind`：业务 token 通常没有该 claim，保持默认 `human`；服务主体调用时可以在自定义 claim
  里写 `service`。

## ADFS

ADFS 2016 及以上提供 OIDC。典型配置：

```json
{
  "issuer": "https://adfs.example.com/adfs",
  "audience": "https://adk-agent.example.com",
  "jwks_url": "https://adfs.example.com/adfs/discovery/keys",
  "tenant_claim": "tenant",
  "roles_claim": "roles",
  "kind_claim": "kind"
}
```

- `issuer` 与 `jwks_url` 从 ADFS 的 discovery 文档抄，不同版本的路径可能不同。
- `audience` 是依赖方信任的标识符，必须与 token 的 `aud` 一致。
- 在 ADFS 的 claim 规则里发出 `tenant` 与 `roles`：`roles` 要是多值数组；AD 里没有对应
  租户属性时，用固定值 claim 或按安全组分映射。
- 多租户场景不要复用同一个 `issuer`；每个签发方一个 `--oidc-config`。

## 控制台浏览器登录（可选）

控制台可以用授权码加 PKCE 登录。`browser` 块的所有 URL 用 discovery 里的端点：

```json
{
  "client_id": "<console-client-id>",
  "authorization_endpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize",
  "token_endpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token",
  "redirect_uri": "https://console.example.com/auth/callback",
  "scopes": ["openid", "profile", "email"],
  "client_secret_env": "ADK_OIDC_CLIENT_SECRET"
}
```

`client_secret_env` 是**环境变量名**，不是密钥本身；值由部署环境注入，不写进配置文件。
回调用例固定是 `<console>/auth/callback`。

## 启动服务

```bash
.venv/Scripts/python.exe -m adk_agent console \
  --agents examples/minimal/agent.py \
  --oidc-config ./oidc-entra.json
```

- `--oidc-config` 与 `--auth-token-env`、`--allow-unauthenticated` 互斥，同时给退出 1。
- `serve`/`serve-many` 的 OIDC 只对 `streamable-http` 生效；stdio 与 OIDC 同时给退出 1。
- 没有 token 或 token 不合法返回 401 `unauthorized`；签发方不可达返回 503
  `identity_unavailable`。
- 角色到能力的映射在服务端：`admin` 全量；`operator`/`ops`/`approver` 与
  `publisher`/`developer` 各有子集；没有匹配角色时只保留 `runs.read`、`sessions.read`、
  `chat.run`。控制台可用 `GET /api/me` 查看当前主体与能力。

## 排障

| 现象 | 先查 |
| --- | --- |
| 401 `unauthorized` | `iss` 是否完全一致、`aud` 是否等于 audience、`kid` 是否在 JWKS、时钟偏差 |
| 401 且日志是 `invalid_claims` | `tenant`/`roles` claim 名是否配错，角色是否是数组 |
| 503 `identity_unavailable` | 内网到 issuer/JWKS 的出站是否放行、DNS 与证书链 |
| 控制台登录循环回登录页 | `redirect_uri` 与注册值是否一致、cookie 是否被代理丢掉 |
| 角色不生效 | token 里是否真的有 `roles`；必要时解一个真实 token 看 claim（不要贴进工单） |

## 不支持的方式

- LDAP 直接绑定、Kerberos/SPNEGO、Windows 集成认证：当前没有实现；需要时另立 ADR，
  作为 identity 适配器接入，不影响现有的 OIDC 路径。
- 用 AD 组名直接当角色：请通过 OIDC claim 映射，不要在做业务判断时查目录。
