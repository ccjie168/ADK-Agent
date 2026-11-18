# SLICE-141 remote-agents CLI 的凭据运行时接入

状态: gated
依据: ADR-0025 第 5 条；SLICE-140 把密文解析接进了工具网关与控制台，`remote-agents` CLI 的 `fetch_agent_card` 仍只用环境变量 provider。

## 意图

1. `remote-agents` 子命令接受 `--credentials-dir`/`--credential-db`（或 `CREDENTIAL_DATABASE_URL`）。配置凭据库时用与工具网关相同的 `RoutingSecretProvider`：两段 `secret://tenant/name` 先解析存储密文，单段引用走 `PrefixedEnvSecretProvider`；未配置时维持环境变量 provider。
2. `register` 的凭据按 `registration.tenant` 作用域解析，`refresh` 按记录租户 `existing.tenant` 解析；跨租户引用按不可用拒绝。
3. fail-closed 语义与 SLICE-140 一致：有密文但缺 `ADK_SECRET_KEKS`、绑定禁用、解密失败或凭据库读取失败都按不可用处理，不回退环境变量。`register` 以退出码 1 失败，`refresh` 沿用现有语义把记录标成 `unreachable`。
4. 命令结束时关闭 Postgres 凭据池（与 `credentials` 命令一致，在同一个事件循环里关闭）。

## 契约（先改）

- `docs/contracts/cli.md` 的 `remote-agents` 小节：新增两个 flag 与凭据解析规则。

## 完成判据

- [x] 配置凭据库后 `register` 用存储密文解析出的值拉取 card -> `test_remote_agents_register_uses_stored_ciphertext`
- [x] 未配置凭据库时 provider 选择不变，环境变量引用照常 -> `test_cli_file_flow`
- [x] 缺 `ADK_SECRET_KEKS` 时仍构造路由 provider 且拒绝密文 -> `test_remote_agents_wires_routing_without_a_key_backend`
- [x] 跨租户引用被拒绝 -> `test_remote_agents_rejects_cross_tenant_credential_ref`
- [x] `refresh` 按记录租户解析，跨租户引用把状态标成 `unreachable` -> `test_remote_agents_refresh_scopes_to_the_record_tenant`
- [x] `refresh` 用记录租户的密文解析出的值拉取 card -> `test_remote_agents_refresh_uses_the_record_credential`
- [x] `list` 与 `disable` 不构造凭据库 -> `test_remote_agents_list_and_disable_ignore_the_credential_store`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `--credentials-dir`，`remote-agents` 只读环境变量 -> 新用例在基线上 argparse 报未知参数或断言拿到环境变量
- [x] 去掉租户作用域包装 -> 跨租户用例拿到别的租户的密文

## 5 问威胁建模

1. **数据**：凭据密文、解析后的明文、租户边界。
2. **调用方**：运维在本机或 CI 里跑的 `adk-agent remote-agents`。
3. **信任边界**：密文存储到 CLI 进程内存；明文只用于一次出站请求的 Authorization 头。
4. **恶意输入最坏结果**：跨租户读取（缓解：租户作用域包装与 AAD）；fail-open（缓解：SLICE-140 的 fail-closed 语义）。
5. **失败是否泄露信息**：只回不可用；告警只记异常类型名，不记记录内容。

## 范围外

- 控制面 `/v1/credentials` 写入端点与轮换命令。
- `remote-agents` 之外的管理命令。
- KMS/Vault。

## 证据

- `docs/evidence/SLICE-141-remote-agent-credentials.txt`
