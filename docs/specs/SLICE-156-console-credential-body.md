# SLICE-156 控制台凭据登记拒绝请求体密文

状态: gated
依据: PROGRESS 缺口清单第 8 条：控制台 `/api/credentials` 仍接受请求体里的 `wrapped_secret`，
客户端可以绕过服务端加密直接写入任意密文。

## 意图

1. `POST /api/credentials` 的请求体出现 `wrapped_secret`、`secret_key_id` 或 `secret_version` 时
   返回 400 `invalid_credential`，不写存储。未配置凭据存储时仍先返回 404
   `credentials_not_configured`（既有顺序）。
2. 密文只能由控制面在写入明文时加密产生；控制台只登记引用元数据。
3. 契约先更新 `docs/contracts/console.md` 的登记段。

## 契约（先改）

- `docs/contracts/console.md` 的 `POST /api/credentials`。

## 完成判据

- [x] 请求体带密文字段返回 400 且不落盘 -> `test_register_rejects_body_supplied_ciphertext`
- [x] 既有登记、列表与审计用例保持通过 -> `test_register_lists_and_audits`
- [x] 全量门禁通过

## 反例

- [x] 基线接受带 `wrapped_secret` 的请求体并返回 201

## 5 问威胁建模

1. **数据**：凭据密文、key id、凭据绑定。
2. **调用方**：admin 控制台用户。
3. **信任边界**：HTTP 请求到凭据存储；密文由客户端提供时跳过服务端加密。
4. **恶意输入最坏结果**：写入无法解密的密文造成 fail-closed 拒绝（缓解：拒绝密文字段）；
   用自选 key id 混淆轮换（缓解：key id 只能由服务端加密路径写入）。
5. **失败是否泄露信息**：固定错误码，不回显密文。

## 范围外

- 控制台写明文 `secret` 的表单（需要单独的安全评审）。
- 控制面 `POST /v1/credentials` 的明文写入（SLICE-142 已定）。

## 证据

- `docs/evidence/SLICE-156-console-credential-body.txt`
