# SLICE-121 租户凭据引用绑定

状态: gated
依据: ADR-0022 决定 5。工具对接自助化分两步，第一步是凭据只以 `secret://` 引用绑定，不存值。租户凭据存储与密钥后端是独立设计，本切片不做。

## 意图（要什么，不写怎么写）

给租户一份可管理的凭据引用清单。管理员登记「租户 + 凭据名 + `secret://` 引用 + 说明」，运行路径按引用取环境变量，跨租户引用被拒绝。

- 绑定记录只含元数据，不含任何密钥值。值仍由进程环境提供。
- 引用的租户段必须等于记录的租户。格式 `secret://<tenant>/<name>`。
- 环境变量名固定为 `ADK_SECRET_<TENANT>_<NAME>`，大写，非字母数字转下划线。
- 单段引用 `secret://name` 保持现有全局行为，不受本切片影响。
- 绑定可登记、列出、停用。停用是幂等的。
- 控制台与 CLI 管理绑定，写操作只给管理员，读按租户过滤。
- 配置了凭据存储时，连接器登记会检查租户引用：引用必须已有同租户的启用绑定，否则拒绝。
- 工具网关按连接器租户包一层作用域提供者，跨租户引用在取用时失败，错误码 `secret_unavailable`。

## 数据形状

`src/adk_agent/core/credentials.py`：

- `CredentialBinding`（frozen，extra=forbid）
  - `credential_id`：`^[A-Za-z0-9][A-Za-z0-9._+-]*$`
  - `tenant`：同 `credential_id` 的模式
  - `secret_ref`：`^secret://[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`
  - `description`：最长 500，默认空
  - `created_by`：非空
  - `created_at`：带时区
  - `enabled`：默认 `True`
  - 校验：`secret_ref` 的租户段必须等于 `tenant`。
- `credential_env_name(reference) -> str`：解析引用并返回环境变量名，非法引用抛 `ValueError`。
- 错误类型：`CredentialStoreError`、`CredentialNotFound`、`CredentialConflict`、`CredentialStoreUnavailable`。

存储键是 `(tenant, credential_id)`。文件布局 `<root>/<tenant>/<credential_id>.json`；Postgres 表 `adk_credentials`，主键 `(tenant, credential_id)`，定义存 jsonb。

## 新增文件

- `src/adk_agent/core/credentials.py`
- `src/adk_agent/registry/credentials.py`
- `src/adk_agent/registry/credentials_postgres.py`
- `tests/test_credentials.py`
- `tests/test_credentials_postgres.py`
- `docs/contracts/credentials.md`
- `docs/evidence/SLICE-121-tenant-credentials.txt`

## 修改文件

- `src/adk_agent/core/ports.py`（`CredentialStore` 端口）
- `src/adk_agent/core/__init__.py`（导出）
- `src/adk_agent/secretstore/providers.py`（`TenantSecretProvider`、`TenantScopedSecretProvider`）
- `src/adk_agent/console.py`（存储参数、三个 `/api/credentials` 路由、Credential 面板）
- `src/adk_agent/cli.py`（`credentials list|register|disable`、控制台与工具网关参数、连接器登记检查）
- `docs/contracts/console.md`、`docs/contracts/cli.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 引用的租户段与记录租户不一致时模型拒绝 -> `tests/test_credentials.py::test_binding_rejects_foreign_tenant_ref`
- [x] 文件 store 往返、按租户隔离 -> `::test_file_store_roundtrip_and_tenant_isolation`
- [x] 同 id 不同定义冲突，停用幂等 -> `::test_file_store_conflict_and_disable`
- [x] Postgres store 往返与隔离 -> `tests/test_credentials_postgres.py::test_postgres_roundtrip_and_isolation`（无 `TEST_POSTGRES_URL` 跳过）
- [x] 引用映射到租户前缀环境变量 -> `::test_tenant_provider_maps_prefixed_env`
- [x] 跨租户引用在作用域提供者处失败 -> `::test_tenant_scoped_provider_rejects_cross_tenant_ref`
- [x] 单段全局引用保持可用 -> `::test_tenant_scoped_provider_allows_global_ref`
- [x] 控制台登记、列出、停用与租户过滤 -> `tests/test_console_credentials.py`
- [x] CLI 登记、列出、停用 -> `tests/test_cli_credentials.py`
- [x] 连接器登记拒绝无绑定或绑定已停用的租户引用 -> `::test_connector_registration_requires_enabled_binding`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：绑定允许把 `secret://other/token` 记在租户 `acme` 名下 -> 期望 `::test_binding_rejects_foreign_tenant_ref` 失败
- [x] 反例 2：文件 store 的 `list("acme")` 返回其他租户记录 -> 期望 `::test_file_store_roundtrip_and_tenant_isolation` 失败
- [x] 反例 3：作用域提供者放行跨租户引用 -> 期望 `::test_tenant_scoped_provider_rejects_cross_tenant_ref` 失败
- [x] 反例 4：连接器登记接受没有启用绑定的租户引用 -> 期望 `::test_connector_registration_requires_enabled_binding` 失败

红态记录: 实现前四个测试文件在收集阶段报 3 个 ImportError，分别缺少 `CredentialBinding` 与 `FileCredentialStore`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户名、凭据名、`secret://` 引用与说明。没有密钥值，没有令牌。
2. **调用方**：管理员登记与停用；租户成员读取清单；工具网关按引用取值。
3. **信任边界**：租户输入到共享存储；存储记录到进程环境变量。
4. **恶意输入最坏结果**：把别的租户的引用记到自己名下，借连接器读取他人凭据（缓解：模型校验引用租户段，作用域提供者在取用时再校验）；用引用名注入路径或环境变量名（缓解：两段都限字符集，环境变量名固定前缀与转写）；停用后仍可用（缓解：登记连接器时要求启用绑定，停用是显式写操作并审计）；把密钥值写进仓库或日志（缓解：记录没有值字段，接口拒绝未知字段）。
5. **失败是否泄露信息**：错误只回错误码，不回引用以外的内容；审计只记租户与凭据名，不记环境变量值。

## 范围外

- 存储密钥值、密钥后端、KMS、轮换。另立 ADR。
- 控制面 `/v1/credentials` 与跨副本 HTTP 客户端。
- 工具网关上的绑定存在性检查。本切片只在连接器登记处检查，网关只做租户作用域。
- 连接器自助申请与审批流。下一步单独切片，复用工具授权审批。
- 修改现有 `PrefixedEnvSecretProvider` 的单段语义。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-121-tenant-credentials.txt`
- 契约: `docs/contracts/credentials.md`
