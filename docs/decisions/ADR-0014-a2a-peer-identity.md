# ADR-0014 A2A 对等身份与调用授权

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

ADR-0003 把 A2A 提供方接到 bearer 中间件上，但只用一个共享 token。运行时的 principal 固定为 `tenant="local"`、`subject="a2a_user"`、`kind="service"`，因此审计只能说明“某个持 token 的调用方跑了一次”，无法区分 peer。`AgentManifest.exposure="a2a"` 目前只是声明，运行时不强制。调用方也没有“哪个 peer 能调哪个 agent 的哪些动作”的映射。

方向评审 Phase D1 要求 per-peer principal、调用授权映射和按 `exposure` 的卡暴露控制。已确认的联邦范围是“先内部 peer”：只支持组织内身份签发，agent card 不对公网开放。不做这一步，A2A 只能作为单租户演示，无法进入多租户试点。

## 决定

1. **身份优先用内部 OIDC，静态 per-peer token 作为回退。** 复用现有 `IdentityProvider` 与 `OidcAuthMiddleware`：peer 用内部 issuer 签发的 JWT 调用，principal 的 tenant 来自 token，peer 标识来自 token subject 到 peer 注册表的映射。回退模式是 `--peer-token-file`，文件里存 `peer_id -> sha256(token)`，中间件对呈递 token 取哈希后查表，不在磁盘存明文。两种模式都配置时启动失败。现有共享单 token 只保留为显式 legacy 模式，并与 peer 身份互斥。

2. **peer 注册表是一等记录。** `PeerIdentity` 含 `peer_id`、`tenant`、`subject`（OIDC 模式下的 token subject）、`kind`、`roles`、`enabled`。文件与 Postgres 各一份存储实现，admin 可写。停用的 peer 在下一次请求即被拒绝，不需要重启。

3. **授权映射独立于工具授权。** `PeerGrant` 含 `peer_id`、`tenant`、`agent_id`、`actions`，`actions` 取 `read` 与 `invoke`：
   - `read` 覆盖 agent card、`tasks/get`、`tasks/resubscribe`；
   - `invoke` 覆盖 `message/send`、`message/stream`、`tasks/cancel`。
   没有 grant 即拒绝。peer 注册本身不授予任何调用权，沿用 ADR-0013 的最小权限做法。`PeerGrant` 存文件或 Postgres，admin 可写，`tenant` 必须与 peer 的租户一致。

4. **在 ASGI 中间件强制，不在 agent 内强制。** 新增 `PeerAuthzMiddleware`，按有界上限缓冲 JSON-RPC 请求体，取出 `method` 映射成动作，再查当前服务的 `agent_id` 是否有对应 grant。拒绝返回 JSON-RPC `-32001` 与 HTTP 403，并写一条 `peer.call` 审计，`status="denied"`。请求体超过上限直接拒绝，不缓存。

5. **agent card 按 `exposure` 和 grant 同时控制。** 服务的 agent 必须带 manifest 且 `exposure="a2a"`；否则 peer 模式拒绝启动，卡路径对任何 peer 返回 404，避免泄露 agent 是否存在。`read` 只对有 grant 的 peer 开放。没有 manifest 的本地 `--agents` 文件仍可用于 legacy 单 token 模式。

6. **审计身份换成 peer。** 成功调用写 `agent.run`，`tenant` 是 peer 的租户，`subject` 是 `peer_id`，不再固定为 `local/a2a_user`。`peer.call` 记录 `target=<agent_id>` 与动作。共享单 token 的 legacy 模式保持原样，便于对比迁移。

7. **限流与配额复用现有键。** `RateLimitMiddleware` 已按 `tenant:subject` 计数；peer principal 接入后自动获得 per-peer 维度，不新增限流器。配额沿用 peer 租户的 `QuotaConfig`。

8. **联邦范围按方向评审确认执行。** v1 只支持组织内 peer，card 不对公网开放，不做多 issuer、OAuth client credentials、跨组织信任与撤销列表。消费方 `remote_agent` 只增加按 peer 命名的凭据环境变量，不引入新的信任模型。

## 切片

- SLICE-090 peer 身份、注册表与强制：`PeerIdentity`、两种身份模式、`PeerGrant` 存储、`PeerAuthzMiddleware`、审计身份切换。
- SLICE-091 管理面：控制台 Peer 面板与三个接口、`adk-agent peers` 命令、把 `peer.call` 拒绝与放行接进现有审计视图。
- SLICE-092 证据与迁移：`docs/contracts/a2a.md`、两种模式互斥的负向验证、legacy 单 token 到 peer 的迁移说明。

## 备选与否决

- **继续用共享单 token，靠额外 header 区分 peer**：header 可伪造，等于没有身份；否决。
- **mTLS**：身份强度更好，但证书签发、轮换与吊销需要新的运维链路；不在 v1。
- **复用 ADR-0011 的工具授权记录**：actor 与动作模型都不同，工具授权按 agent 版本授权工具，peer 授权按 peer 授权 agent 动作；混用会让两张表语义互相污染；否决。
- **在 agent 内部检查 peer**：agent 看到的是消息，不是 JSON-RPC 方法与 card 请求；无法覆盖 `read` 动作；否决。
- **v1 直接做跨组织联邦**：需要多 issuer、撤销与公网 card 暴露，超出当前确认范围；否决。

## 后果

- A2A 从“单租户共享 token”升级为“可审计、可授权的 peer 协作”，为 Phase D2 的远端 agent 目录提供身份基础。
- 多一层 peer 注册表与授权表；peer 模式要求服务的 agent 带 manifest。
- JSON-RPC 方法级授权需要中间件读取请求体，必须设置上限，否则成为内存风险。
- legacy 共享 token 模式与 peer 模式互斥，迁移期需要一次配置切换，缓存与已加载 agent 需要重启生效。
- 仍不做公网联邦、跨组织信任与凭据撤销列表。

## 确认记录

2026-11-14 会话确认，三点均按本 ADR 采纳：

1. 身份用内部 OIDC 优先、哈希 per-peer token 回退，共享单 token 降为 legacy 且互斥。
2. 授权按 `peer -> agent_id -> {read, invoke}` 建表，无记录即拒绝，admin 才能写。
3. v1 只做组织内 peer，card 不公开，不做多 issuer 与跨组织信任。
