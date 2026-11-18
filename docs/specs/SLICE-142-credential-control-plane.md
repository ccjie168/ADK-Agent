# SLICE-142 控制面凭据写入端点

状态: gated
依据: ADR-0025 第 7 条。SLICE-139 给了 CLI `--secret-stdin`，控制面仍只有控制台的元数据登记，没有 admin 的凭据写入与停用端点。

## 意图

1. `POST /v1/credentials`：admin 提交元数据与可选的单行明文 `secret`，服务端用
   `ADK_SECRET_KEKS` 的当前 KEK 做信封加密后只存密文；响应与审计都不含明文或密文。
2. `POST /v1/credentials/{credential_id}/disable?tenant=T`：admin 停用，幂等。
3. 请求体只接受 `tenant`、`credential_id`、`secret_ref`、`description`、`secret`；其他字段
   （尤其 `wrapped_secret`）一律 400 `invalid_credential`。
4. `serve-registry` 新增 `--credentials-dir`/`--credential-db`（或 `CREDENTIAL_DATABASE_URL`）与
   `ADK_SECRET_KEKS` 接线；`ADK_SECRET_KEKS` 非法时启动退出 1 并给出提示。
5. 明文只存在于请求处理期间；日志只记异常类型，不记请求体。

## 契约（先改）

- `docs/contracts/registry_service.md` 新增两个端点与错误码。
- `docs/contracts/cli.md` 的 `serve-registry` 小节补凭据库与 KEK 参数。

## 完成判据

- [x] 明文经服务端加密后只存密文，响应不含 `wrapped_secret` -> `test_register_encrypts_a_plaintext_secret`
- [x] 只有元数据时行为不变 -> `test_register_metadata_only`
- [x] 没有密钥后端时拒绝明文 -> `test_register_secret_needs_a_key_backend`
- [x] 请求体带 `wrapped_secret` 被拒绝 -> `test_register_rejects_ciphertext_in_the_body`
- [x] 多行、空或超长明文被拒绝 -> `test_register_rejects_multiline_or_empty_secrets`
- [x] 非 admin 403 -> `test_register_requires_admin`
- [x] 停用幂等且只审计一次 -> `test_disable_is_idempotent_and_audited`
- [x] 未配置凭据存储返回 503 -> `test_credential_store_unavailable_when_not_configured`
- [x] 静态 token 下停用必须给 `tenant` -> `test_disable_needs_a_tenant_without_oidc`
- [x] `serve-registry` 构造端点并拒绝非法 `ADK_SECRET_KEKS` -> `test_builds_credential_routes`、`test_invalid_kek_exits`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `/v1/credentials`，请求 404；`--credentials-dir` 是未知参数
- [x] 去掉 admin 检查 -> 非 admin 用例拿到 201

## 5 问威胁建模

1. **数据**：凭据明文、密文、租户边界、KEK。
2. **调用方**：带 admin 角色或静态 token 的运维、控制台与 CLI 之外的自动化。
3. **信任边界**：明文从客户端跨网络到控制面进程，再以密文落库；KEK 只在服务端。
4. **恶意输入最坏结果**：非 admin 写入（缓解：admin 先于租户检查）；请求体塞入他人密文
   （缓解：拒绝未知字段）；超长或多行明文（缓解：长度与换行校验）；明文进日志（缓解：不记录请求体）。
5. **失败是否泄露信息**：只回固定错误码；审计只记 target 与 key id。

## 范围外

- 轮换命令与 `KeyBackend.rewrap()`（下一片，已在会话中确认方向）。
- 控制台凭据面板的明文写入表单。
- KMS/Vault。

## 证据

- `docs/evidence/SLICE-142-credential-control-plane.txt`
