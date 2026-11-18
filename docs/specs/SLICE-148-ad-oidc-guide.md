# SLICE-148 企业内网身份认证文档：AD / Entra ID / ADFS

状态: gated
依据: 会话确认内网优先，AD 集成属于身份认证而非密钥管理；ADR-0025 与 `docs/contracts/credentials.md` 把密钥管理分开。

## 意图

1. 新增 `docs/guides/ad-oidc.md`：先决条件、`OidcConfig` 字段表、Entra ID 与 ADFS 配置样例、
   控制台 PKCE 浏览器登录、启动参数、排障与不支持的方式。
2. 样例必须能通过 `OidcConfig`/`OidcBrowserConfig` 校验，不能是“看起来像”的配置文件。
3. 安装手册的控制台小节指向这份文档。
4. 明确写出：LDAP/Kerberos/SPNEGO 不在当前实现内，需要时另立 ADR；密钥管理见 ADR-0025 与凭据契约。

## 契约（先改）

- 没有对外接口变化；文档只描述现有 OIDC 配置与 `--oidc-config` 行为。

## 完成判据

- [x] 文档包含先决条件、配置格式、Entra、ADFS、浏览器登录、排障与不支持的方式 -> `test_guide_covers_the_required_sections`
- [x] 所有 JSON 样例通过 `OidcConfig`/`OidcBrowserConfig` 校验 -> `test_every_json_example_validates`
- [x] 缺 `issuer`/`audience` 的样例会被模型拒绝 -> `test_guide_examples_require_the_issuer_and_audience`
- [x] 文档写明 `--oidc-config`、ADR-0007、凭据契约、Kerberos 限制与 `client_secret_env` -> `test_guide_names_the_limits_and_decisions`
- [x] 全量门禁通过

## 反例

- [x] 基线没有这份文档，新用例读取文件失败
- [x] 样例写错字段或漏必填字段会让模型校验用例失败

## 5 问威胁建模

1. **数据**：issuer、audience、JWKS 地址与角色 claim 名；不含客户端密钥。
2. **调用方**：内网运维与开发者。
3. **信任边界**：浏览器到控制台、服务到 issuer/JWKS。
4. **恶意输入最坏结果**：把 client secret 写进配置文件（缓解：`client_secret_env` 只写变量名）；
   audience 或 issuer 配错导致身份混用（缓解：文档要求用真实 token 核对，服务端始终校验）。
5. **失败是否泄露信息**：失败只回 401/503 固定错误码；文档提醒不要把真实 token 贴进工单。

## 范围外

- LDAP/Kerberos/SPNEGO 适配器（需要单独 ADR）。
- 密钥管理后端（ADR-0026）。
- IdP 侧的组、角色与条件访问配置。

## 证据

- `docs/evidence/SLICE-148-ad-oidc-guide.txt`
