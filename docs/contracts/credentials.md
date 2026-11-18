# 租户凭据引用契约

绑定只保存元数据，不保存密钥值。值可来自密文或进程环境，变量名由引用推导。

## `CredentialBinding`

```json
{
  "credential_id": "crm",
  "tenant": "acme",
  "secret_ref": "secret://<tenant>/<name>",
  "description": "CRM outbound credential",
  "created_by": "admin",
  "created_at": "2026-11-16T08:00:00Z",
  "enabled": true
}
```

- 示例中的 `<tenant>` 与 `<name>` 是占位符，实际记录里是具体名称。
- `credential_id`、`tenant`：`^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$`（最长 128）。
- `secret_ref`：`^secret://[A-Za-z0-9._-]{1,128}/[A-Za-z0-9._-]{1,128}$`，租户段必须等于 `tenant`。
- 未知字段、缺失字段、无时区的时间戳都拒绝。
- 记录里默认没有令牌、口令或任何值字段。

## 引用到环境变量

`secret://<tenant>/<name>` 映射到 `ADK_SECRET_<TENANT>_<NAME>`。两段各自大写，非字母数字转下划线。例如 `secret://acme/crm-prod` 读 `ADK_SECRET_ACME_CRM_PROD`。

单段引用 `secret://name` 仍是现有的全局映射 `ADK_SECRET_NAME`，语义不变。

## 存储

- 键是 `(tenant, credential_id)`。
- 文件布局：`<root>/<tenant>/<credential_id>.json`。重复登记相同内容幂等，不同内容冲突。
- Postgres：`adk_credentials(tenant text, credential_id text, definition jsonb, updated_at timestamptz, PRIMARY KEY (tenant, credential_id))`。
- 停用把 `enabled` 改成 `false`，重复停用幂等。

## 控制台

`GET /api/credentials?tenant=`：列出调用方租户的绑定；`admin` 可指定其他租户，越权 403 `tenant_forbidden`。未配置存储 404 `credentials_not_configured`。

`POST /api/credentials`：仅 `admin`。请求体是 `CredentialBinding`，`created_by` 与 `created_at` 由服务端覆盖为调用主体与当前时间。冲突 409 `credential_conflict`，非法 400 `invalid_credential`，存储失败 503 `credential_store_unavailable`。成功 201 返回记录，并写 `credential.register` 审计。

`POST /api/credentials/{credential_id}/disable`：仅 `admin`。不存在 404 `credential_not_found`，成功返回停用后的记录，并写 `credential.disable` 审计。

## CLI

`adk-agent credentials list --tenant TENANT [--credentials-dir DIR | --credential-db URL]`

`adk-agent credentials register --tenant TENANT --id ID --secret-ref REF [--description TEXT] [--credentials-dir DIR | --credential-db URL]`

`adk-agent credentials disable --tenant TENANT --id ID [--credentials-dir DIR | --credential-db URL]`

- 未给显式后端时读 `CREDENTIAL_DATABASE_URL`；显式文件与数据库同时给出或显式与环境变量冲突时退出 2。
- 成功输出记录的 JSON；失败 stderr 输出原因并退出 1。
- 错误消息不回显任何环境变量值。

## 连接器登记约束

配置了凭据存储时，连接器报文里的租户引用必须满足：

- `secret_ref` 的租户段等于连接器的 `tenant`。
- 同租户存在启用中的绑定。

不满足返回 400 `credential_unbound`，不写连接器。连接器 `tenant` 为空时不得使用两段租户引用。未配置凭据存储的部署保持现有行为。

工具网关按连接器租户包装提供者。两段引用在取用时再次校验租户，不符返回工具错误 `secret_unavailable`。单段全局引用不受影响。


## 信封加密（ADR-0025）

- 记录可带 `wrapped_secret`（对象）、`secret_key_id` 与 `secret_version`；密文用 AES-256-GCM，
  数据密钥由 KEK 包裹，AAD 是 `adk-credential:<tenant>:<credential_id>`。
- keyring 从 `ADK_SECRET_KEKS` 读取：JSON 对象，含 `active`（当前 key id）与 `keys`（key id 到 base64 编码的 32 字节 KEK）。
- `TenantSecretProvider` 先按 `secret_ref` 找启用且带密文的记录并解密，失败抛不可用；凭据库读取失败
  同样按不可用处理；没有密文时回退 `ADK_SECRET_<TENANT>_<NAME>` 环境变量。
- `credentials register [--secret-stdin]` 从标准输入读值并加密写入，缺 `ADK_SECRET_KEKS` 退出 1；值必须是单行；
- 凭据响应只返回元数据，不返回 `wrapped_secret` 或任何密文载荷。
  输出只含元数据，不含明文。
- 轮换保留旧 key id 用于解密；keyring 缺失旧 key id 时拒绝解密。
- `KeyBackend.rewrap(wrapped, aad)` 只把数据密钥换到当前 KEK 下重新包裹，凭据值的密文与 nonce 不变，
  不解密明文；key id 已是当前值时验证 AAD 后原样返回。
- `CredentialStore.replace_wrapped(tenant, credential_id, wrapped_secret, secret_key_id)` 只更新这两个字段，
  保留 `enabled`、`description` 等并发修改；记录不存在抛 `CredentialNotFound`。
  文件存储在记录旁创建 `<id>.json.lock` 并用 OS 文件锁串行化读改写，跨进程的 `disable` 不会被覆盖；
  Postgres 用 `jsonb_set` 只改这两个键，`disable` 也只改 `enabled`。
- `credentials rewrap --tenant T [--dry-run]` 逐条把非当前 key id 的记录换到当前 KEK；
  已是当前 key id 或没有密文的记录计入 `skipped`；输出 `{tenant, rewrapped, skipped, dry_run}`。
