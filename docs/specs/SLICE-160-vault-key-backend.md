# SLICE-160 Vault/OpenBao Transit 密钥后端

状态: gated
依据: ADR-0027（2026-11-19 会话确认）；PROGRESS 缺口清单第 5 条。

## 意图

1. `secretstore/keys.py` 新增 `VaultKeyBackend`，实现 `KeyBackend` 四个方法：凭据值仍用
   AES-256-GCM（AAD 不变），DEK 由 Transit `encrypt`/`decrypt`/`rewrap` 封装与升级。
2. payload 采用 `v: 2` 且 `backend: "vault"`；本地 KEK 记录保持 `v: 1`；两种后端都按各自的
   格式校验，跨后端记录直接报 `unsupported secret format`（fail-closed）。
3. `load_key_backend` 按 `ADK_SECRET_BACKEND` 选择：缺省 `local`，`vault` 读取
   `ADK_VAULT_ADDR`/`ADK_VAULT_KEY`/挂载点/命名空间/CA/超时与令牌文件或令牌变量，配置冲突
   或非法时抛 `KeyBackendError`（CLI 已统一退出 1）。
4. 传输层用标准库 `urllib` + `ssl.create_default_context`，不新增依赖；403、不可达、超时、
   非法响应映射为固定 `KeyBackendError` 文案，不回显令牌或 URL 内容。
5. 契约先更新 `docs/contracts/credentials.md` 与 `cli.md`。

## 契约（先改）

- `docs/contracts/credentials.md` 的密钥后端段。
- `docs/contracts/cli.md` 的 keyring 段。

## 完成判据

- [x] wrap/unwrap 往返与错误 AAD 拒绝 -> `test_wrap_and_unwrap_roundtrip`、`test_unwrap_rejects_the_wrong_aad`
- [x] rewrap 只升级 DEK 包装，值密文与 nonce 不变 -> `test_rewrap_moves_the_dek_to_the_current_version`
- [x] `current_key_id` 取 Transit 版本 -> `test_current_key_id_uses_the_transit_version`
- [x] `v: 1` 与 `backend: local` 的 payload 被拒绝 -> `test_payload_validation`
- [x] 配置构造与令牌文件读取 -> `test_load_key_backend_builds_the_vault_backend`
- [x] 令牌冲突/本地 keyring 冲突/非回环 http/超时非法/未知后端被拒 -> `test_load_key_backend_rejects_conflicting_vault_config`、`test_load_key_backend_rejects_plain_http_off_loopback`、`test_load_key_backend_rejects_an_invalid_timeout`、`test_load_key_backend_rejects_an_unknown_backend`
- [x] 本地 `v: 1` 记录仍可读写 -> `test_local_backend_still_reads_v1_records`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `VaultKeyBackend`，`ADK_SECRET_BACKEND` 未被识别，Vault 配置被忽略

## 5 问威胁建模

1. **数据**：凭据值、DEK、Vault 令牌、Transit 密文。
2. **调用方**：持有凭据存储与 keyring 配置的服务进程。
3. **信任边界**：进程到内网 Vault；令牌来自只读文件或环境变量。
4. **恶意输入最坏结果**：令牌或明文进入日志（缓解：错误文案固定，不回显令牌/URL 内容）；
   跨后端记录被错误解封（缓解：payload 校验与 fail-closed）；明文 HTTP 泄露令牌
   （缓解：仅允许回环地址用 http）。
5. **失败是否泄露信息**：只给固定错误与 HTTP 状态码，不含响应体。

## 范围外

- 迁移命令 `credentials migrate --to vault`（ADR-0027 切片 4，需要单独评审）。
- AppRole/Kubernetes 认证与 Vault Agent 注入（令牌模式先行）。
- 错误码细分（`vault_unavailable`/`vault_denied`）与安装手册更新。
- live Vault 集成测试（默认跳过，需 `TEST_VAULT_ADDR`）。

## 证据

- `docs/evidence/SLICE-160-vault-key-backend.txt`
