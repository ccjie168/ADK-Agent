# ADR-0025 租户凭据的密钥后端：信封加密与本地 KEK

状态: Accepted   日期: 2026-11-18   签字: Jie CAO（会话确认）

## 背景

SLICE-121 的租户凭据只存引用，值放在进程环境变量 `ADK_SECRET_<TENANT>_<NAME>`；`TenantSecretProvider` 在父进程解析 `secret://`。这有三个问题。

- 密钥值与进程生命周期绑定，无法随凭据记录轮换，也无法按租户撤销。
- 多副本部署时每个进程都要注入全部租户的密钥，泄露面随副本数放大。
- 控制面没有凭据写入路径，运维只能改部署配置。

ADR-0022 第 5 条要求“租户凭据存储需要单独的密钥后端设计”。这份 ADR 回答该问题。它不改变“凭据值只在父进程解析、worker 不持有凭据”的既有边界。

## 决定

1. **端口。** 新增 `KeyBackend` 端口：`wrap(plaintext, aad) -> wrapped`、`unwrap(wrapped, aad) -> plaintext`、`current_key_id()`、`rotate()`。实现放在 `secretstore/`，与 `SecretProvider` 分开：前者管密钥材料，后者按 `secret://` 解析。

2. **信封加密。** 每条凭据用一次性数据密钥（AES-256-GCM）加密，数据密钥由租户主密钥（KEK）包裹。AAD 绑定 `tenant`、`credential_id` 与格式版本，密文不能跨租户或跨记录搬运。

3. **v1 后端是本地文件 KEK。** 主密钥从 `ADK_SECRET_KEK`（32 字节，base64）读取，可来自文件挂载的 Secret。KEK 只在启动时读取，不落盘、不进日志、不进审计。KMS/Vault 作为同一端口的后续实现，不在 v1 引入新依赖。

4. **存储。** `CredentialBinding` 增加可选的 `wrapped_secret`、`secret_key_id` 与 `secret_version`；密钥值字段只存密文。文件与 Postgres 存储都按 `(tenant, credential_id)` 写入。

5. **解析顺序。** `TenantSecretProvider` 先查存储里的密文并用 KEK 解开；没有密文时回退到环境变量，保留兼容；两者都没有时按既有错误返回不可用。解出的明文只在调用瞬间存在，不写缓存。

6. **轮换。** `rotate()` 生成新 KEK，旧 KEK 以 key id 保留在 keyring 中用于解开旧记录；重新包裹数据密钥，不重加密凭据值。没有旧 key id 的记录在轮换后拒绝解开（fail-closed）。

7. **写入路径。** CLI `credentials register --secret-stdin`（不接受 argv 传值）加密后写存储；控制面 `POST /v1/credentials` 与 `POST /v1/credentials/{id}/disable` 由 admin 调用。审计只记 `credential.register`/`credential.disable` 与 key id，不记密文。

8. **读取审计。** 每次解密不单独写审计，避免高频写入；工具调用的 `tool.call` 审计已覆盖使用点。解密失败写 `credential.decrypt_failed`，带 key id 与原因码。

## 备选与否决

- **继续用环境变量**：无法轮换与按租户撤销，多副本泄露面大；否决为长期方案，保留为兼容回退。
- **只上云 KMS**：v1 的部署面是单机与 Compose，引入云依赖会把本地路径与云路径分成两套；暂缓，作为端口实现。
- **明文存数据库并靠访问控制**：数据库备份即明文，违背“只存引用”的初衷；否决。
- **每租户一把 KEK**：隔离更强，但 KEK 数量与撤销复杂度上升；v1 用单 KEK 加 AAD 隔离，后续可演进。

## 后果

- 凭据值从环境变量迁移到密文需要一次运维动作；兼容回退保证迁移不是一次性切换。
- KEK 在进程内存中，属于 v1 的残余风险；生产建议挂载 Secret 并限制进程读取权限。
- 轮换需要保留旧 key id；丢失旧 KEK 会使旧密文不可解，按 fail-closed 处理。
- 控制面新增凭据写入端点，需要 admin 鉴权与审计；worker 仍不接触明文。

## 切片（待确认后分配）

1. `KeyBackend` 端口与本地 KEK 实现、信封加密与 AAD。
2. 存储字段扩展与 `TenantSecretProvider` 解析顺序。
3. CLI `--secret-stdin` 与控制面凭据端点。
4. 轮换、keyring 与审计。

## 确认记录

2026-11-18 会话确认按草案实现：本地 KEK 信封加密、AAD 绑定租户与凭据 id、环境变量保留兼容回退、KMS 后续走同一端口。
