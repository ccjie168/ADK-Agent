# ADR-0027 凭据密钥后端：HashiCorp Vault / OpenBao Transit

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

ADR-0026 只定义了密钥后端的选型框架，具体后端未定。2026-11-19 会话确认：内网方向选择
**HashiCorp Vault / OpenBao**，通过 Transit 引擎封装凭据的数据密钥（DEK）。OpenBao 是
Vault 的 API 兼容分支，同一实现两者通用。

现有的信封加密（ADR-0025）已经固定：每条凭据一个随机 DEK，凭据值用 AES-256-GCM 加密
（AAD `adk-credential:<tenant>:<credential_id>`），DEK 由 `KeyBackend` 封装。本 ADR 只替换
“DEK 由谁封装/解封”，不改凭据值密文、存储字段与运行时解析语义。

## 决定

1. **实现 `VaultKeyBackend`，复用 `KeyBackend` 端口。** `wrap`、`unwrap`、`rewrap`、
   `current_key_id` 四个方法，调用方不按后端分支。凭据值仍是本地 AES-256-GCM，DEK 由
   Transit 封装与解封。

2. **不新增依赖，用标准库 HTTP。** Vault Transit 是简单的 JSON over HTTPS；使用
   `urllib.request` + `ssl.create_default_context`，超时默认 5 秒。`hvac` / `httpx` 作为
   可选实现被否决，避免为一个后端引入新依赖。

3. **配置（显式选择）。**
   - `ADK_SECRET_BACKEND=vault` 显式启用；缺省仍是 `local`。
   - `ADK_VAULT_ADDR`（必填，`https://`；`http://` 只允许回环地址）。
   - `ADK_VAULT_KEY`（必填，Transit key 名）；`ADK_VAULT_TRANSIT_MOUNT` 默认 `transit`。
   - 令牌：`ADK_VAULT_TOKEN_FILE`（首选，POSIX 要求 0600/0400）或 `ADK_VAULT_TOKEN`，二者
     同时设置或都缺失时启动退出 1；令牌不写日志、不进错误文案。
   - 可选 `ADK_VAULT_NAMESPACE`、`ADK_VAULT_CACERT`；TLS 校验默认开启，不能关闭。
   - Vault 模式与 `ADK_SECRET_KEKS`/`ADK_SECRET_KEKS_FILE` 同时配置时启动退出 1。

4. **密文 payload 升级到 `v: 2`，带 `backend`。**
   - Vault 记录：`{"v": 2, "backend": "vault", "key_id": "vault:v<N>", "wrapped_dek":
     "vault:v<N>:<...>", "nonce": ..., "ciphertext": ...}`。
   - 本地 KEK 记录保持 `v: 1` 格式，新写入不变；`v: 2` 且 `backend=local` 视为非法。
   - 读取按记录的 `backend` 分派：Vault 部署读到 `v: 1` 本地记录直接报“后端不匹配”，不尝试
     跨后端解封（fail-closed）。

5. **轮换与 key id。**
   - `current_key_id` 取 Transit encrypt 返回的 `vault:v<N>`。
   - `rewrap` 调 Transit `/rewrap`，把 wrapped DEK 换到当前版本，凭据值密文不动。
   - 轮换本身由运维执行 `vault write -f transit/keys/<key>/rotate`；应用不管理密钥版本。
   - 旧版本在 Vault 的 `min_decryption_version` 之下时解封失败，按解密失败处理。

6. **失败语义与 ADR-0026 一致。** 不可达、403、密钥禁用、解密失败都映射到 `KeyBackendError`，
   `TenantSecretProvider` 写 `credential.decrypt_failed` 审计并 fail-closed；没有本地回退，
   DEK 不缓存。错误码细分（`vault_unavailable`/`vault_denied`）随实现切片补，不改对外 503。

7. **切换后端需要迁移切片。** 从本地 KEK 切到 Vault 时，已有记录是 `v: 1`；新增
   `credentials migrate --to vault`：用本地 KEK 解封 DEK，再用 Transit 重新封装，凭据值密文
   与 nonce 不变。迁移前 Vault 部署读旧记录会 fail-closed。反向迁移同理，是否需要另行决定。

8. **测试。** 单元测试注入伪 HTTP 层（不起网络），覆盖 wrap/unwrap/rewrap、403、超时、
   非法响应、payload 校验与配置互斥；live 集成用 `TEST_VAULT_ADDR` + dev 模式 Vault 或
   OpenBao，默认跳过。契约更新 `docs/contracts/credentials.md` 与 `cli.md`。

## 备选与否决

- **Vault KV 存取 KEK**：密钥材料进入应用进程，失去 Transit 的意义；否决。
- **引入 `hvac`**：功能重复且新增依赖；否决，标准库足够。
- **自动探测后端**：配置错误会静默换后端，违背显式选择与 fail-closed；否决。
- **跨后端自动读取旧记录**：需要两套密钥同时在场，扩大泄露面；否决，改为显式迁移。
- **DEK 进程内缓存**：降低延迟但扩大驻留面；暂不做。

## 后果

- 凭据解析多一次内网 HTTPS 调用；Vault 成为凭据读写路径的可用性依赖，需要运维监控。
- 密钥轮换交给 Vault，应用侧 `credentials rewrap` 负责把旧 DEK 包装升级。
- 本地 KEK 仍保留给单机开发与没有 Vault 的部署，语义不变。
- 实现顺序：payload v2 与分派 → `VaultKeyBackend` 与配置 → 契约与文档 → 迁移命令。

## 切片（待确认后分配）

1. payload `v: 2`、`backend` 字段与读取分派（本地后端兼容 `v: 1`）。
2. `VaultKeyBackend`、配置解析、`load_key_backend` 的 vault 模式与错误映射。
3. 契约、安装手册与运维手册更新。
4. `credentials migrate --to vault`（需要单独评审迁移语义）。

## 确认记录

2026-11-19 会话确认：采纳 Vault / OpenBao Transit 作为凭据密钥后端；标准库 HTTPS、显式
`ADK_SECRET_BACKEND=vault`、`v: 2` payload 带 `backend`、本地 `v: 1` 保持兼容、跨后端读取
fail-closed、迁移单独切片。实现顺序按“切片”一节的 1 到 4 推进。
