# SLICE-090 A2A peer 身份、授权与强制

状态: merged
依据: ADR-0014 第 1 到 7 条。

## 意图（要什么，不写怎么写）

A2A 现在只有一个共享 token，审计身份固定为 `local/a2a_user`，`exposure="a2a"` 只是声明。这一刀把 A2A 提供方升级成按 peer 的身份、按 agent 动作的授权与真实审计身份。

- 新增 `PeerIdentity`、`PeerGrant`、文件与 Postgres 存储。
- 身份两种模式：内部 OIDC（token subject 映射 peer），或哈希 per-peer token 文件。
- 新增授权中间件：按 JSON-RPC 方法与 HTTP 方法映射成 `read` / `invoke`，无 grant 即拒绝。
- 审计身份换成 peer：`tenant` 与 `subject` 来自 peer 记录。
- peer 模式要求 `--manifest` 且 `exposure="a2a"`，否则拒绝启动。
- 共享单 token 保留为 legacy 模式，与 peer 模式互斥。

## 新增文件

- `src/adk_agent/core/peers.py`
- `src/adk_agent/registry/peers.py`、`src/adk_agent/registry/peers_postgres.py`
- `src/adk_agent/registry/peer_grants.py`、`src/adk_agent/registry/peer_grants_postgres.py`
- `src/adk_agent/identity/peer_tokens.py`
- `src/adk_agent/a2a_peer.py`（两个中间件与动作映射）
- `tests/core/test_peers.py`、`tests/registry/test_peer_stores.py`
- `tests/test_a2a_peer.py`
- `docs/contracts/a2a.md`
- `docs/evidence/SLICE-090-a2a-peer-identity.txt`
- `docs/specs/SLICE-090-a2a-peer-identity.md`

## 修改文件

- `src/adk_agent/core/ports.py`（`PeerStore`、`PeerGrantStore`）
- `src/adk_agent/core/__init__.py`、`src/adk_agent/registry/__init__.py`
- `src/adk_agent/runtime/audit_proxy.py`（principal 与 quota policy 可为按请求的 callable）
- `src/adk_agent/a2a.py`（中间件装配与 runner 接线）
- `src/adk_agent/cli.py`（`serve-a2a` 的 peer 参数与互斥）
- `tests/test_a2a.py`、`tests/test_a2a_runtime.py`、`tests/test_cli_a2a_runtime.py`
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
PeerIdentity {
  peer_id: str (^[A-Za-z0-9][A-Za-z0-9._+-]*$),
  tenant: str (safe name),
  subject: str,
  kind: "human" | "service" | "agent",
  roles: list[str] = [],
  enabled: bool = true
}

PeerGrant {
  peer_id: str,
  tenant: str,          # 必须等于 peer.tenant
  agent_id: str (safe name),
  actions: list["read" | "invoke"]  # 非空
}

PeerStore:      get(peer_id) -> PeerIdentity | None, list() -> list[PeerIdentity], put(identity)
PeerGrantStore: get(peer_id, agent_id) -> PeerGrant | None, list() -> list[PeerGrant], put(grant)

peer token 文件: {"peer-a": "<64 hex sha256(token)>"}

文件存储: <peer-dir>/peers/<peer_id>.json, <peer-dir>/grants/<peer_id>/<agent_id>.json
Postgres: adk_peers(peer_id pk, tenant, subject, kind, roles jsonb, enabled)
          adk_peer_grants(peer_id, agent_id, tenant, actions jsonb, pk(peer_id, agent_id))
```

```text
A2A 动作映射:
  GET  任意路径（agent card） -> read
  POST JSON-RPC method:
    message/send, message/stream, tasks/cancel -> invoke
    tasks/get, tasks/resubscribe               -> read
    其他 method                                 -> 拒绝
  其他 HTTP 方法 -> 拒绝

中间件执行顺序（外到内）:
  _TraceContextMiddleware -> 身份 -> PeerAuthzMiddleware -> RateLimit -> app
```

## 完成判据（可执行）

- [x] `PeerIdentity` 与 `PeerGrant` 校验 -> `tests/core/test_peers.py`
- [x] 文件 peer 与 grant 存储幂等 -> `tests/registry/test_peer_stores.py::test_file_roundtrip`
- [x] Postgres 存储（有 `TEST_POSTGRES_URL` 时）-> `::test_postgres_roundtrip`
- [x] token 文件只接受 64 hex 且大小写不敏感 -> `tests/test_a2a_peer.py::test_token_file`
- [x] 未知 token 返回 401 -> `::test_unknown_token_unauthorized`
- [x] OIDC subject 映射到 peer，租户不符拒绝 -> `::test_subject_mapping`
- [x] 停用 peer 被拒绝 -> `::test_disabled_peer`
- [x] 无 grant 的 invoke 返回 -32001 与 403 -> `::test_invoke_denied`
- [x] `invoke` 放行 message/send，`read` 放行 tasks/get -> `::test_action_mapping`
- [x] 无 `read` 时 card 返回 404 -> `::test_card_hidden`
- [x] 请求体超限返回 413 -> `::test_body_too_large`
- [x] 拒绝写 `peer.call` 审计 -> `::test_denial_audited`
- [x] `agent.run` 审计身份是 peer 的 tenant 与 peer_id -> `::test_run_audited_as_peer`
- [x] `serve-a2a` 参数互斥与 `exposure` 校验 -> `tests/test_cli_a2a_runtime.py`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import PeerIdentity` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.a2a_peer import PeerAuthzMiddleware` -> 当前 `ImportError`
- [x] 反例 3：`serve-a2a --peer-dir X` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先创建 `docs/contracts/a2a.md`，并更新 `docs/contracts/cli.md` 的 `serve-a2a` 段。

## 5 问威胁建模（10 分钟）

1. **数据**：peer 标识、租户、subject、角色、token 哈希、agent 动作授权。
2. **调用方**：组织内 peer 的 A2A 客户端、控制面运维。
3. **信任边界**：外部请求进入 A2A 服务；OIDC 签发方到 peer 注册表；JSON-RPC 请求体到授权判定。
4. **恶意输入最坏结果**：伪造 peer 身份（缓解：OIDC 验签或哈希 token 比对，用量恒定时间比较）；跨租户调用（缓解：grant 租户必须等于 peer 租户，subject 映射校验租户）；超大请求体撑爆内存（缓解：1 MiB 上限，超限 413）；未知方法绕过（缓解：白名单映射，未知即拒）；停用 peer 继续调用（缓解：每次请求查存储，不缓存）；授权拒绝无痕迹（缓解：`peer.call` 审计）。
5. **失败是否泄露信息**：无权读取 card 返回 404；错误只回固定码；不回显 token 或 subject。

## 范围外

- 控制台 Peer 面板与 `adk-agent peers` 命令（SLICE-091）。
- 消费方按 peer 命名的凭据管理。
- 多 issuer、撤销列表、mTLS。
- peer 维度的独立速率上限（沿用 `tenant:subject` 键）。

## 证据

- 反例红：`docs/evidence/SLICE-090-a2a-peer-identity.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，两个 peer 一放一拒、审计身份不同
