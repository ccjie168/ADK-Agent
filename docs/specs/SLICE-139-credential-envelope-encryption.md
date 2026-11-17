# SLICE-139 凭据信封加密与本地 KEK

状态: gated
依据: ADR-0025 第 1 至 6 条。租户凭据此前只有环境变量；本切片交付密钥后端端口、本地 KEK、信封加密、存储字段、解析顺序与 CLI 密文写入。

## 意图

1. `secretstore/keys.py`：`KeyBackend` 端口与 `LocalKeyBackend`，AES-256-GCM 信封加密，AAD 绑定租户与凭据 id。
2. `CredentialBinding` 增加 `wrapped_secret`、`secret_key_id`、`secret_version`。
3. `TenantSecretProvider` 先按 `secret_ref` 找密文记录并解密；只有完全没有密文时才回退环境变量。
   有密文但缺后端、绑定全被禁用或解密失败时 fail-closed，不回退。
4. CLI `credentials register --secret-stdin` 从标准输入读值、加密后写入；不接受 argv 传值。
5. keyring 从 `ADK_SECRET_KEKS` 读取（`active` + `keys`），轮换保留旧 key id 用于解密。

## 契约（先改）

- `docs/contracts/credentials.md`：密文字段、AAD、解析顺序、`--secret-stdin` 与 keyring。

## 完成判据

- [x] 信封加解密与 AAD 绑定 -> `tests/secretstore/test_keys.py`
- [x] 未知 key id、格式错误、轮换后旧记录可解 -> 同上
- [x] 解析优先密文、回退环境变量 -> `tests/secretstore/test_secret_providers.py`
- [x] CLI 从 stdin 写入密文且输出不含明文 -> `tests/test_cli_credentials.py`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `LocalKeyBackend` 与密文字段 -> 新用例收集失败或断言失败

## 5 问威胁建模

1. **数据**：凭据明文、数据密钥、KEK、密文与 AAD。
2. **调用方**：父进程服务与 CLI；工具网关的运行时接入在下一片。
3. **信任边界**：密钥材料与存储；worker 不接触明文。
4. **恶意输入最坏结果**：密文跨记录搬运（缓解：AAD 绑定租户与凭据 id）；丢失 KEK（缓解：保留旧 key id，缺失 fail-closed）；明文进日志（缓解：输出只含元数据）。
5. **失败是否泄露信息**：解密失败只回不可用，不回显密文或密钥。

## 范围外

- 运行时接入：`serve-tool-gateway` 与控制台远程 agent 仍使用环境变量 provider，下一片改为
  `TenantSecretProvider(backend, credentials)`；本切片只交付密钥后端、存储字段与 CLI 写入。
- 控制面 `/v1/credentials` 写入端点（ADR-0025 切片 3）。
- 记录级轮换命令与 `credential.decrypt_failed` 审计（切片 4）。
- KMS/Vault 实现。

## 证据

- `docs/evidence/SLICE-139-credential-envelope-encryption.txt`
