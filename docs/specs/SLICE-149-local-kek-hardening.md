# SLICE-149 本地 KEK 加固：只读 keyring 文件与权限检查

状态: gated
依据: ADR-0026 第 3 条（会话确认的过渡方案）。内网允许的密钥服务尚未确定，先把本地 KEK 的
密钥面从环境变量收窄到受保护的文件。

## 意图

1. 新增 `load_key_backend()`：从 `ADK_SECRET_KEKS`（JSON 值）或 `ADK_SECRET_KEKS_FILE`（只读文件）
   读取 keyring，二选一；同时设置抛 `KeyBackendError`，调用方按配置错误退出 1。
2. `LocalKeyBackend.from_file()`：POSIX 上拒绝组或其他用户可读的文件（0600/0400）；Windows
   跳过权限检查；文件缺失或非法内容抛 `KeyBackendError`，错误信息不含密钥。
3. 所有构造点（`serve-tool-gateway`、`serve-registry`、`remote-agents`、控制台、
   `credentials register|rewrap`）改用 `load_key_backend()`；错误提示同时提到两个变量名。
4. 契约、安装手册与 ADR-0026 同步；ADR-0026 转为 Accepted。

## 契约（先改）

- `docs/contracts/credentials.md` 与 `docs/contracts/cli.md` 写明两个变量、互斥与 POSIX 权限。
- `docs/guides/install-and-use.md` 的生产建议改为只读文件。

## 完成判据

- [x] 从文件读取 keyring -> `test_load_key_backend_reads_a_file`
- [x] 两个变量同时设置被拒绝 -> `test_load_key_backend_rejects_env_and_file`
- [x] POSIX 上组/其他用户可读的文件被拒绝 -> `test_keyring_file_permissions_are_checked`
- [x] 文件缺失给出固定错误 -> `test_keyring_file_missing_is_rejected`
- [x] CLI 从文件读取并加密写入 -> `test_cli_stores_a_secret_from_a_keyring_file`
- [x] 全量门禁通过

## 反例

- [x] 基线只读 `ADK_SECRET_KEKS`，设置 `ADK_SECRET_KEKS_FILE` 会被忽略（CLI 报“缺 KEK”）
- [x] 基线没有权限检查，0644 的 keyring 文件照常加载

## 5 问威胁建模

1. **数据**：KEK keyring、凭据密文。
2. **调用方**：部署该服务的运维。
3. **信任边界**：Secret 卷/只读文件到进程内存。
4. **恶意输入最坏结果**：同机其他用户读到 keyring（缓解：POSIX 权限检查）；同时配置两个来源
   导致“以为换了来源其实没换”（缓解：启动拒绝）；错误信息回显密钥（缓解：固定文案）。
5. **失败是否泄露信息**：只回文件名与固定错误；不回显 keyring 内容。

## 范围外

- KMS/Vault/HSM 的具体后端（ADR-0026 选型后另立切片）。
- Windows 上的 ACL 检查（只跳过，不伪造检查）。
- `credential.decrypt_failed` 审计（ADR-0026 切片 2）。

## 证据

- `docs/evidence/SLICE-149-local-kek-hardening.txt`
