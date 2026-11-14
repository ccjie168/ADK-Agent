# SLICE-093 远端 agent 目录记录

状态: merged
依据: ADR-0015 第 1、2、5 条。

## 意图（要什么，不写怎么写）

ADR-0015 定了远端条目是独立记录、信任靠固定 card 摘要。这一刀落类型、存储、拉取、控制台接口与命令；市场页合并留给 094。

- 新增 `RemoteAgent` 与文件/Postgres 存储，复用 `--peer-dir`/`--peer-db`。
- 新增受约束的 card 拉取：带凭据、不跟随重定向、有超时与体积上限、按原始字节算 sha256。
- 注册要求 peer 存在且启用，card 的 agent 名称与 `remote_id` 一致，租户与 peer 租户一致。
- 刷新区分固定、已变化、不可达；变化时保留已批准的 `card_digest`，另记 `observed_digest`，重新注册即重新批准。
- 控制台四个接口与 CLI `remote-agents list|register|refresh|disable`。
- 凭据经 `PrefixedEnvSecretProvider` 解析，只用于拉 card。

## 新增文件

- `src/adk_agent/core/remote_agents.py`
- `src/adk_agent/registry/remote_agents.py`、`src/adk_agent/registry/remote_agents_postgres.py`
- `tests/core/test_remote_agents.py`
- `tests/registry/test_remote_agent_store.py`
- `tests/test_console_remote_agents.py`
- `tests/test_cli_remote_agents.py`
- `docs/evidence/SLICE-093-remote-agent-catalog.txt`
- `docs/specs/SLICE-093-remote-agent-catalog.md`

## 修改文件

- `src/adk_agent/core/ports.py`（`RemoteAgentStore`）
- `src/adk_agent/core/__init__.py`、`src/adk_agent/registry/__init__.py`
- `src/adk_agent/console.py`（四个接口、`remote_agents` 参数）
- `src/adk_agent/cli.py`（`remote-agents` 子命令与 `console` 接线）
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
RemoteAgent {
  remote_id: safe name,
  tenant: safe name,
  peer_id: safe name,
  agent_card_url: https://...（回环 http 允许，不嵌入凭据）,
  credential_ref: "secret://..." | null,
  label: string,
  card_digest: "sha256:<64 hex>",
  observed_digest: "sha256:<64 hex>" | null,
  checked_at: datetime (UTC),
  status: "pinned" | "changed" | "unreachable",
  enabled: bool
}

fetch_agent_card(url, credential=None, *, client=None, max_bytes=1048576)
  -> (digest, card: dict)
  GET, 带 Bearer（有凭据时），follow_redirects=False，超时 5 秒，
  超限或非 JSON 抛固定错误。

GET    /api/remote-agents?tenant=T        -> [RemoteAgent]
POST   /api/remote-agents                 -> RemoteAgent（注册或重新批准）
POST   /api/remote-agents/{id}/refresh    -> RemoteAgent
POST   /api/remote-agents/{id}/disable    -> RemoteAgent

CLI:
  remote-agents list [--tenant T]
  remote-agents register --id ID --tenant T --peer P --card-url URL [--credential-ref REF] [--label L]
  remote-agents refresh --id ID
  remote-agents disable --id ID
  存储参数复用 --peer-dir / --peer-db。
```

规则：

- 注册与刷新只有 admin；读按租户可见。
- `peer_id` 不存在或未启用返回 404 `peer_not_found`；记录租户与 peer 租户不一致返回 400 `tenant_mismatch`。
- card 拉取失败按原因返回 502 `card_unreachable`、502 `card_unauthorized`、502 `card_too_large` 或 502 `card_invalid`；card 名称不符 400 `card_name_mismatch`。
- 凭据解析失败 503 `secret_unavailable`。
- 刷新摘要一致记 `pinned` 并清空 `observed_digest`；不一致保留 `card_digest`，写 `observed_digest` 并记 `changed`；拉取失败保留两者，记 `unreachable`，`checked_at` 更新。
- 注册写 `remote_agent.register`，刷新写 `remote_agent.refresh`，停用写 `remote_agent.disable`。

## 完成判据（可执行）

- [x] `RemoteAgent` 校验 URL、凭据引用、摘要与时区 -> `tests/core/test_remote_agents.py`
- [x] 文件存储往返与覆盖 -> `tests/registry/test_remote_agent_store.py::test_file_roundtrip`
- [x] Postgres 存储（有 `TEST_POSTGRES_URL` 时）-> `::test_postgres_roundtrip`
- [x] 拉取成功并算出摘要 -> `tests/test_console_remote_agents.py::test_register_pins_card`
- [x] 名称不符被拒 -> `::test_register_name_mismatch`
- [x] 未知或停用 peer 被拒 -> `::test_register_requires_peer`
- [x] 租户不一致被拒 -> `::test_register_tenant_mismatch`
- [x] 刷新摘要变化记 changed -> `::test_refresh_changed`
- [x] 刷新不可达记 unreachable 并保留摘要 -> `::test_refresh_unreachable`
- [x] 重新注册重新批准 -> `::test_reregister_repins`
- [x] 非 admin 写被拒与租户过滤 -> `::test_admin_only_and_tenant`
- [x] 未配置存储 404 -> `::test_not_configured`
- [x] CLI 文件流程 -> `tests/test_cli_remote_agents.py::test_cli_file_flow`
- [x] CLI 未知 id 退出 1 -> `::test_cli_missing_exits`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import RemoteAgent` -> 当前 `ImportError`
- [x] 反例 2：`GET /api/remote-agents` -> 当前 404（路由不存在）
- [x] 反例 3：`adk-agent remote-agents list --peer-dir X` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：peer、card 地址、出站凭据引用、card 摘要、标签、租户。
2. **调用方**：控制台 admin、CLI 操作者。
3. **信任边界**：控制台到远端 card；`SecretProvider` 到出站凭据；记录到市场视图（094）。
4. **恶意输入最坏结果**：凭据外泄（缓解：只经 `SecretProvider`，不写进记录与审计，错误不回显）；SSRF 打内网（缓解：URL 校验只允许 https 或回环 http，只对已注册 peer 的地址拉取，admin 才能写）；超大 card 撑爆内存（缓解：1 MiB 上限）；card 被替换（缓解：固定摘要，变化即标为不可信）；跨租户看到别家条目（缓解：租户过滤与 403）。
5. **失败是否泄露信息**：只回固定错误码；不返回响应体、凭据或远端内部细节。

## 范围外

- 市场页合并、信任徽标与刷新按钮（094）。
- 出站调用与 `egress=third_party` 审计（095）。
- 从控制台加载或对话远端 agent。
- 定时刷新。

## 证据

- 反例红：`docs/evidence/SLICE-093-remote-agent-catalog.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，回环 card 服务器与真实 httpx 验证固定、变化、不可达三种状态
