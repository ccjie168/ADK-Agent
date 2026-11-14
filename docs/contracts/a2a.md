# A2A 提供方契约（ADR-0014）

A2A 服务的路径由 `rpc_path` 决定：agent card 与 JSON-RPC 都在该前缀下。没有配置 `rpc_path` 时使用根路径。本契约只覆盖提供方；消费方仍是 ADK 的 `RemoteA2aAgent`。

## 认证模式

| 模式 | 配置 | 身份来源 | 授权 |
| --- | --- | --- | --- |
| legacy | `--auth-token-env` | 固定 principal `tenant=local`、`subject=a2a_user`、`kind=service` | 无，持 token 即可调用 |
| peer-oidc | `--oidc-config FILE` 与 peer 存储 | JWT 的 `sub` 到 `PeerIdentity.subject` 映射 | `PeerGrant` |
| peer-token | `--peer-token-file FILE` 与 peer 存储 | 呈递 token 的 sha256 到 token 文件匹配 | `PeerGrant` |

- peer 模式与 legacy 互斥；同时配置启动失败。
- peer 模式必须提供 `--manifest`，且 manifest 的 `exposure` 为 `a2a`；否则启动失败。
- peer 模式不提供 `--allow-unauthenticated`。
- 所有路径都要身份；A2A 没有豁免路径，agent card 也在身份中间件之后。


## peer 身份

`PeerIdentity` 的 `tenant` 必须与呈递身份的租户一致，否则拒绝。`enabled=false` 的 peer 在请求时即被拒绝。认证成功后请求的 principal 就是 peer 的 `tenant`/`peer_id`/`kind`/`roles`。

审计身份随 peer：`agent.run` 的 `tenant` 与 `principal` 来自 peer，不再是 `local/a2a_user`。legacy 模式保持原样。

## 出站调用审计

消费方 `remote_agent(..., audit=sink, peer_id="...")` 在每次 HTTP 请求上写一条 `a2a.call`：

- `egress="third_party"`，`target="<peer_id>/<agent name>"`，`tenant` 与 `principal` 取构造参数（默认 `local` 与 `a2a_consumer`，kind 为 `service`）。
- `status="ok"` 当响应码小于 500；`>= 500` 或传输异常记 `"error"`。传输异常在记完之后原样抛出。
- `args_hash` 是 `"<method> <path>"` 的哈希。不记录请求体、响应体、完整 URL 或凭据。
- `trace_id` 优先取当前 invocation 的 trace，取不到则新建。`latency_ms` 是实际请求耗时。
- 审计写入失败只记日志，不改变调用结果。
- 这是本地边界。远端内部的审计事件不在这里，只能按 trace id 关联；本契约不承诺跨组织端到端可验证。

不给 `audit` 时 `remote_agent` 行为不变；给了 `audit` 却没给 `peer_id` 抛 `ValueError`。

### 记录形状

```text
PeerIdentity {
  peer_id: safe name,
  tenant: safe name,
  subject: non-empty string,
  kind: "human" | "service" | "agent",
  roles: [string],
  enabled: bool
}

PeerGrant {
  peer_id: safe name,
  tenant: safe name,          # 必须等于 peer.tenant
  agent_id: safe name,
  actions: ["read" | "invoke"]  # 非空且不重复
}
```

### 存储

- `--peer-dir DIR`：`<DIR>/peers/<peer_id>.json` 与 `<DIR>/grants/<peer_id>/<agent_id>.json`。写入用临时文件加原子替换，重复写覆盖。
- `--peer-db URL`：Postgres 表 `adk_peers` 与 `adk_peer_grants`，按 `(peer_id, agent_id)` 主键 upsert。
- `--peer-token-file FILE`：JSON 对象，`peer_id -> 64 位十六进制 sha256(token)`。文件里不放明文 token，匹配用常量时间比较。

## 授权

动作只有两个。

| 请求 | 动作 |
| --- | --- |
| `GET` 任意路径（agent card） | `read` |
| JSON-RPC `message/send`、`message/stream`、`tasks/cancel` | `invoke` |
| JSON-RPC `tasks/get`、`tasks/resubscribe` | `read` |
| 其他 JSON-RPC 方法、其他 HTTP 方法 | 拒绝 |

- 没有对应 `PeerGrant` 即拒绝。`PeerGrant.tenant` 必须等于 peer 的租户。
- JSON-RPC 调用被拒时返回 HTTP 403 与 JSON-RPC 错误 `-32001`，`id` 原样回传。请求体不是合法 JSON-RPC 时按未知方法拒绝，错误 `id` 为 `null`。
- 任何 `GET` 无权读取返回 404，避免泄露 agent 是否存在。A2A 只有 agent card 一个 GET 入口。
- 每次拒绝写一条 `peer.call` 审计，`status="denied"`，`target` 是 agent id，`args_hash` 是方法名或 `card`。放行不额外写 `peer.call`，成功调用仍由 `agent.run` 记录。

## 限制

- JSON-RPC 请求体上限 1 MiB，超限返回 413 `request_too_large`，不缓存请求体。
- 速率限制沿用 `tenant:subject` 键，peer 模式下即 per-peer 维度。
- 配额按 peer 租户的 `QuotaConfig` 计算。

## 错误

| 状态 | 错误码 | 含义 |
| --- | --- | --- |
| 401 | `unauthorized` | 缺少或无效的 bearer 凭据 |
| 403 | `forbidden` | 有身份但无对应动作授权 |
| 403 | JSON-RPC `-32001` | 同上，用于 JSON-RPC 请求 |
| 404 | `not_found` | card 无权读取，或路径不存在 |
| 413 | `request_too_large` | JSON-RPC 请求体超过 1 MiB |
| 503 | `identity_unavailable` | OIDC 签发方暂时不可用 |
| 503 | `peer_store_unavailable` | peer 或授权存储不可达 |
