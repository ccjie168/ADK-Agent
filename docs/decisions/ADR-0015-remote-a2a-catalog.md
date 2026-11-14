# ADR-0015 远端 A2A agent 作为目录条目

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

ADR-0014 让 A2A 提供方按 peer 身份授权，peer 与授权也能在控制台和命令里管理。但目录与市场只列本进程或本注册表里的已发布版本，别的 peer 暴露了什么 agent，平台上看不到。方向评审 Phase D2 要求把 A2A peer 暴露的 agent 作为一等目录条目，带信任标记，并写清跨组织审计边界。

现在的空白有三处。远端 agent 没有记录形状；没有“这张 card 是不是上次看到的那张”的判断；调用远端时的审计边界没有约定。直接照搬本地版本模型也不行，远端没有工件字节、没有我们的版本签名，硬塞进 `AgentManifest` 会把 schema 和加载路径分叉。

## 决定

1. **远端条目是独立记录，不是 manifest 的一种。** 新增 `RemoteAgent`：

   ```text
   remote_id: safe name
   tenant: safe name
   peer_id: safe name          # 必须对应一个已配置的 PeerIdentity
   agent_card_url: https://...（回环 http 允许）
   credential_ref: "secret://..." | null
   label: string
   card_digest: "sha256:<64 hex>"
   checked_at: datetime
   status: "pinned" | "changed" | "unreachable"
   enabled: bool
   ```

   文件与 Postgres 各一份存储，admin 可写。注册表继续只存带工件与签名的本地版本，两条路径不混。

2. **信任靠固定 card 摘要，不靠每次重新信任。** 注册与刷新用 `credential_ref` 经 `SecretProvider` 解析出的凭据拉取 card，要求 card 的 agent 名称与 `remote_id` 一致，把原始 card 字节的 sha256 存下来。后续 `refresh` 显式重新拉取：摘要一致记 `pinned`，不一致记 `changed`，拉取失败或凭据解析失败记 `unreachable`。`changed` 与 `unreachable` 仍显示在目录里，但带警告，绝不当成可信条目。列表请求不触发网络拉取。凭据只用于 card 拉取，不进入记录响应与审计；解析失败只回固定错误码。

3. **v1 只做目录，不可加载、不可对话。** 远端条目并入 `GET /api/registry`，`source="remote"`，附 `trust` 块（摘要、状态、检查时间）。控制台的 Load chat、卸载与置换只对本地版本生效。真正的出站调用仍由本地 agent 内部的 `remote_agent` 消费方完成，不在本 ADR 扩大。

4. **跨组织审计边界写清楚。** 入站 peer 调用按 ADR-0014 以 peer 身份审计。出站调用由本地运行时按本地 agent 记一次 run，并补一条 `egress="third_party"` 的事件，标注远端 agent 与 peer，trace id 透传。我们的审计只覆盖自己这一侧，远端内部事件不在我们的可见范围，只能按 trace id 关联。本 ADR 不承诺跨组织可验证的端到端审计。

5. **目录可见不等于调用授权。** 列出一个远端条目不需要也不产生 `PeerGrant`；真正的 `read`/`invoke` 仍由 ADR-0014 的授权在调用点检查。管理远端条目只有 admin 能写。

6. **联邦范围不变。** 仍只支持组织内 peer，agent card 不对公网开放，不做多 issuer、跨组织信任锚与撤销列表。

## 切片

- SLICE-093 `RemoteAgent` 类型、文件/Postgres 存储、控制台四个接口与 `remote-agents` 命令。
- SLICE-094 市场页合并远端条目、信任徽标与刷新入口。
- SLICE-095 出站 `egress=third_party` 审计、契约与证据收口。

## 备选与否决

- **在 `AgentManifest` 里加远端来源字段**：远端没有工件字节和我们的版本签名，会让发布、加载与生命周期三处都出现分支；否决。
- **列表时实时拉取 card**：延迟与可用性都不可控，还会把目录请求变成出站探测；否决。
- **拉到什么 card 就信什么**：无法发现被替换的 card，信任无从谈起；否决。
- **v1 就让远端 agent 可在控制台开聊**：需要 per-peer 出站凭据管理与新的密钥路径，超出目录范围；否决。
- **把目录条目当成调用授权**：混淆发现与授权，违反最小权限；否决。

## 后果

- 市场能看到 peer 暴露的 agent，并区分固定、已变化、不可达三种信任状态。
- 多一层远端条目存储与控制台面板；v1 不改运行时加载路径。
- 新增一条受 `SecretProvider` 管理的出站凭据路径，只用于拉取 card，需要像连接器一样审计与轮换。
- 跨组织审计只到本地边界，运维需要知道关联靠 trace id。
- 后续若要远端可执行，需要新 ADR 解决出站凭据与远端审计关联。

## 确认记录

2026-11-14 会话确认，三点均按本 ADR 采纳：

1. 远端条目是独立记录，不扩展 `AgentManifest`。
2. 信任用固定 card 摘要与显式刷新，变化或不可达仍显示但标为不可信。
3. v1 只做目录，不可加载；出站审计只覆盖本地侧并写清边界。

草稿补充：拉取 card 需要作为客户端的出站凭据，记录里用 `credential_ref` 引用，经 `SecretProvider` 解析，只用于 card 拉取。
