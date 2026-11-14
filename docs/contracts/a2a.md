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
