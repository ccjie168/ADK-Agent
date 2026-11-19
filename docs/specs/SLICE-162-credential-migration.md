# SLICE-162 本地 KEK 到 Vault 的凭据迁移命令

状态: gated
依据: ADR-0027 切片 4；2026-11-19 会话确认的三项语义（新增命令、只对 migrate 放宽互斥、
遇错停止并保留原记录）。

## 意图

1. 新增 `credentials migrate --to vault --tenant T [--dry-run] [--credentials-dir|--credential-db]`。
2. 迁移逐条把 `v: 1` 记录的数据密钥用本地 KEK 解封（`LocalKeyBackend.unwrap_dek`），再用
   Transit 封装（`VaultKeyBackend.wrap_dek`），凭据值密文与 nonce 不变；用 `unwrap_dek` 复核
   迁移后的数据密钥一致，不解密凭据值。
3. 没有密文或已是 `v: 2` 的记录计入 `skipped`；任一记录失败立即停止，已迁移的保持 v2，
   未处理的保持 v1；重跑幂等。
4. `--dry-run` 只计数不写入；输出 `{tenant, migrated, skipped, dry_run}`。
5. 只有该命令允许本地 keyring 与 Vault 配置共存（`load_key_backend(allow_local=True)` 与
   `load_local_backend`）；其他命令与服务仍互斥。契约与安装手册同步。

## 契约（先改）

- `docs/contracts/cli.md` 的 `credentials` 段。
- `docs/contracts/credentials.md` 的密钥后端段。
- `docs/guides/install-and-use.md` 的迁移说明。

## 完成判据

- [x] 本地记录迁到 v2 并可被 Vault 后端解封 -> `test_migrate_rewrites_local_records`
- [x] `--dry-run` 不写入 -> `test_migrate_dry_run_does_not_write`
- [x] 无密文记录计入 skipped -> `test_migrate_skips_records_without_ciphertext`
- [x] Vault 失败即停且保留原记录 -> `test_migrate_stops_on_a_vault_failure`
- [x] 缺本地 keyring 或非 vault 模式被拒 -> `test_migrate_requires_the_local_keyring`、`test_migrate_requires_vault_mode`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `credentials migrate` 子命令，六个用例在基线上失败

## 5 问威胁建模

1. **数据**：凭据值密文、数据密钥、本地 KEK、Vault 令牌。
2. **调用方**：执行迁移的运维。
3. **信任边界**：本地 keyring 与 Vault 同时在场。
4. **恶意输入最坏结果**：迁移把错误数据写坏（缓解：先解封 DEK、迁移后复核、保留值密文）；
   失败留下混合状态（缓解：遇错停止、幂等重跑）；令牌或明文进输出（缓解：不打印明文，
   固定错误文案）。
5. **失败是否泄露信息**：输出只有计数与固定错误，不含密文、DEK、令牌。

## 范围外

- 跨租户批量迁移（`--tenant` 必填）。
- Vault 反向迁移到本地 KEK。
- 迁移审计（CLI 写存储不写审计，与 `rewrap` 一致）。

## 证据

- `docs/evidence/SLICE-162-credential-migration.txt`
