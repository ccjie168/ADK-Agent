# SLICE-143 凭据轮换：数据密钥重新包裹

状态: gated
依据: ADR-0025 第 6 条与第 1 条（2026-11-18 会话确认增加 `rewrap`）。SLICE-139 交付了 KEK keyring 与信封加密，但没有轮换路径。

## 意图

1. `KeyBackend` 端口增加 `rewrap(wrapped, aad) -> wrapped`：用旧 key id 解开数据密钥，
   用当前 KEK 重新包裹，凭据值的密文与 nonce 不变，全程不出现凭据明文；AAD 校验失败、
   key id 不可用或 payload 非法时抛 `KeyBackendError`；key id 已是当前值时校验 AAD 后原样返回。
2. `CredentialStore` 端口增加 `replace_wrapped(tenant, credential_id, wrapped_secret, secret_key_id)`：
   只更新密文与 key id。文件存储在 `<id>.json.lock` 上取 OS 文件锁后先读后写，跨进程串行；
   Postgres 用 `jsonb_set` 只改这两个键，`disable` 也只改 `enabled`；并发的 `disable`、
   `description` 修改不会被覆盖；记录不存在抛 `CredentialNotFound`。
3. `credentials rewrap --tenant T [--dry-run]`：逐条把非当前 key id 的记录换到当前 KEK；
   没有密文或已是当前 key id 的记录计入 `skipped`；输出 `{tenant, rewrapped, skipped, dry_run}`；
   缺 `ADK_SECRET_KEKS` 退出 1。
4. 轮换仍是“重建 keyring、保留旧 key id”，本切片不删除旧 key。

## 契约（先改）

- `docs/contracts/credentials.md`：`rewrap` 端口与命令语义。
- `docs/contracts/cli.md`：`credentials rewrap`。
- ADR-0025 第 1 条与确认记录。

## 完成判据

- [x] 重新包裹后数据密钥用当前 KEK，值密文不变且仍可解出明文 -> `test_rewrap_moves_the_data_key_to_the_active_key`
- [x] key id 已是当前值时原样返回 -> `test_rewrap_is_idempotent_on_the_active_key`
- [x] AAD 不符、key id 不可用或 payload 形状非法时拒绝 -> `test_rewrap_rejects_a_different_aad`、`test_rewrap_rejects_an_unknown_key_id`、`test_rewrap_rejects_a_malformed_payload`
- [x] 只合并密文与 key id，保留并发停用 -> `test_file_store_replace_wrapped_merges_only_the_ciphertext`、`test_file_store_replace_wrapped_keeps_a_concurrent_disable`、`test_postgres_replace_wrapped_keeps_a_disable`
- [x] 文件存储的读改写在跨进程锁内 -> `test_store_lock_blocks_another_writer`、`test_replace_wrapped_reads_after_taking_the_lock`
- [x] `credentials rewrap` 先 dry-run 后落盘，重复运行全部跳过 -> `test_cli_rewraps_to_the_active_key`
- [x] 超长 `credential_id`/`tenant` 被模型与路由拒绝（400），不再落到文件系统 -> `test_register_rejects_an_overlong_identifier`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `rewrap`/`replace_wrapped`，命令不存在
- [x] 把 rewrap 实现成解密后重加密 -> 无从验证；本切片用“密文与 nonce 不变”的断言锁定不触碰值密文

## 5 问威胁建模

1. **数据**：数据密钥、KEK、凭据值密文、AAD。
2. **调用方**：持有 `ADK_SECRET_KEKS` 的运维。
3. **信任边界**：旧 KEK 与新 KEK 同时存在于进程内存的 keyring。
4. **恶意输入最坏结果**：把别的记录的密文搬进某条记录（缓解：AAD 绑定租户与凭据 id，
   `rewrap` 用记录自身的 AAD 验证）；轮换后旧记录解不开（缓解：保留旧 key id，失败 fail-closed）。
5. **失败是否泄露信息**：只回 `KeyBackendError` 的固定文案；命令错误只打印异常信息，不回显密钥。

## 范围外

- 删除旧 KEK 与 rewrap 后的审计（ADR-0025 第 8 条的 `credential.decrypt_failed` 仍延后）。
- KMS/Vault 的 `rewrap` 实现。
- `serve-registry` 之外的在线轮换调度。

## 证据

- `docs/evidence/SLICE-143-credential-rotation.txt`
