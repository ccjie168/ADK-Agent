# SLICE-150 凭据解密失败审计与 keyring 边界收口

状态: gated
依据: ADR-0026 第 6 条与 ADR-0025 第 8 条（会话确认的过渡切片）；SLICE-149 验证留下的低风险边界。

## 意图

1. `TenantSecretProvider` 接受可选 `audit`；解密失败或带密文但无密钥后端时写
   `credential.decrypt_failed` 审计：`target` 是 `<tenant>/<credential_id>`，
   `agent_ref.version` 是 `credential.<key id>`，`error_code` 是 `decrypt_failed` 或
   `key_backend_unavailable`；不记明文与密文。审计失败只记日志，不改变 fail-closed 结果。
2. 审计用当前 invocation 的主体（租户一致时），否则用服务主体；成功解析不写审计。
3. 工具网关与控制台把各自的 `AuditSink` 传给 provider；只构造一个 sink，避免重复写。
4. keyring 边界：无效 UTF-8 映射为 `KeyBackendError`；空的 `ADK_SECRET_KEKS_FILE` 视为未设置，
   不与 `ADK_SECRET_KEKS` 误报冲突。
5. 契约与 CLI 帮助补齐两个 keyring 变量名。

## 契约（先改）

- `docs/contracts/credentials.md` 的审计与解析语义。
- `docs/contracts/cli.md` 与 `docs/contracts/registry_service.md` 的 keyring 措辞。

## 完成判据

- [x] 解密失败写审计，带 key id 与错误码，不含明文 -> `test_decrypt_failure_writes_an_audit_event`
- [x] 缺密钥后端写 `key_backend_unavailable` -> `test_missing_key_backend_writes_an_audit_event`
- [x] 成功解析不写审计 -> `test_successful_resolution_does_not_audit`
- [x] 非 UTF-8 keyring 文件映射为 `KeyBackendError` -> `test_keyring_file_must_be_utf8`
- [x] 空的 `ADK_SECRET_KEKS_FILE` 不与环境变量冲突 -> `test_empty_file_variable_does_not_conflict`
- [x] 全量门禁通过

## 反例

- [x] 基线 provider 没有审计：解密失败只抛 `SecretNotFound`
- [x] 基线对非 UTF-8 keyring 抛 `UnicodeDecodeError`，`serve-registry` 会打出 traceback

## 5 问威胁建模

1. **数据**：凭据密文、密钥、主体与审计记录。
2. **调用方**：工具网关、控制台与远程 agent 的凭据解析。
3. **信任边界**：存储到父进程内存；审计只写元数据。
4. **恶意输入最坏结果**：审计泄露明文/密文（缓解：只用 ref、key id 与错误码）；
   审计失败掩盖 fail-closed（缓解：审计异常只记日志，解析仍抛 `SecretNotFound`）。
5. **失败是否泄露信息**：错误码固定，不回显密钥或密文。

## 范围外

- KMS/Vault/HSM 后端的错误码细分（`kms_unavailable`/`kms_denied` 随后端切片）。
- 成功解密的逐次审计（ADR-0025 明确不写）。

## 证据

- `docs/evidence/SLICE-150-decrypt-failed-audit.txt`
