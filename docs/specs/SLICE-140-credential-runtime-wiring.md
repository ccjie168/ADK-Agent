# SLICE-140 凭据密钥后端的运行时接入

状态: gated
依据: ADR-0025 第 5 条。SLICE-139 交付了密钥后端与 `TenantSecretProvider`，但 `serve-tool-gateway`、控制台远程 agent 与 `remote-agents` CLI 仍只用环境变量 provider，写入的密文从未被消费。

## 意图

1. 新增 `RoutingSecretProvider`：两段 `secret://tenant/name` 交给 `TenantSecretProvider`（内部再回退环境变量），单段引用交给 `PrefixedEnvSecretProvider`。
2. `serve-tool-gateway` 新增 `--credentials-dir`/`--credential-db`，配置时构造 `RoutingSecretProvider(LocalKeyBackend.from_env(), store, prefixed)`；未配置时保持环境变量行为。
3. 控制台在已有 `--credentials-dir`/`--credential-db` 且 `ADK_SECRET_KEKS` 存在时，用同一 provider 解析远程 agent 凭据。
4. `remote-agents` CLI 的 `fetch_agent_card` 接入留到下一片；本切片不改它的 provider。
5. fail-closed 语义不变：有密文但缺后端、绑定禁用或解密失败不回到环境变量。

## 契约（先改）

- `docs/contracts/cli.md`、`docs/contracts/credentials.md`、`docs/contracts/tool_gateway.md`（若存在 provider 说明）。

## 完成判据

- [x] 两段引用解析密文，单段引用走环境变量 -> `test_routing_provider`
- [x] `serve-tool-gateway` 配置凭据库后连接器凭据从密文解析 -> `test_tool_gateway_uses_stored_credentials`
- [x] 控制台远程 agent 在配置凭据库与 KEK 时使用 `RoutingSecretProvider` -> 控制台构造路径（无独立用例）
- [x] 未配置凭据库时行为不变 -> 既有用例
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `RoutingSecretProvider`，工具网关只读环境变量 -> 新用例收集失败或断言失败

## 5 问威胁建模

1. **数据**：凭据密文、解析后的明文、租户边界。
2. **调用方**：工具网关、控制台、CLI。
3. **信任边界**：密文存储到父进程内存。
4. **恶意输入最坏结果**：跨租户读取（缓解：租户作用域包装与 AAD）；fail-open（缓解：SLICE-139 的 fail-closed）。
5. **失败是否泄露信息**：只回 `secret_unavailable`。

## 范围外

- 控制面 `/v1/credentials` 写入端点与轮换命令。
- KMS/Vault。

## 证据

- `docs/evidence/SLICE-140-credential-runtime-wiring.txt`
