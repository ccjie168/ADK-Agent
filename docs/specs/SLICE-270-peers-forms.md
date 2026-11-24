# SLICE-270 对端与远端目录表单（PeersView）

状态: draft
依据: 用户反馈「页面能力应在页面配置」；接口 `POST /api/peers`、`POST /api/peers/{id}/disable`、
`POST /api/remote-agents` 均已存在（`peers.manage`）

## 意图

PeersView 从只读表格变成可管理：

1. `peers.manage` 下「注册对端」表单：`peer_id`、租户、主体、类型（service/agent/human）→ `POST /api/peers`；
   错误码映射 `invalid_peer` / `peer_tenant_immutable` / `peer_store_unavailable`。
2. 每行「禁用」→ `POST /api/peers/{id}/disable`。
3. 「登记远端 Agent」表单：`remote_id`、租户、`peer_id`、`agent_card_url`、`credential_ref`（可选）、标签
   → `POST /api/remote-agents`（服务端会抓取卡片并记录摘要）。
   错误码映射 `invalid_remote_agent`、`peer_not_found`、`tenant_mismatch`、`secret_unavailable`、
   `remote_agent_tenant_immutable`、`remote_agent_store_unavailable`、`remote_agent_unreachable`、
   `remote_agent_card_mismatch`，其余回退状态码。
4. 所有请求经 `post()` 包装，网络失败提示「请求失败: 网络错误」；结果消息在表格上方。

后端无改动。凭据只以 `secret://` 引用形式提交，页面不接触密钥值。

## 契约（先改）

无对外接口变化；三个端点已在 `docs/contracts/console.md` 记录（`GET/POST /api/peers`、
`POST /api/peers/{id}/disable`、`POST /api/remote-agents`）。

## 完成判据

- [x] 对端注册表单按 `peers.manage` 显示并提交 `peer_id` -> `test_peers_view_registers_peer`
- [x] 对端可禁用 -> `test_peers_view_disables_peer`
- [x] 远端登记表单提交 `agent_card_url`/`credential_ref` -> `test_peers_view_registers_remote_agent`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过

## 反例

基线（SLICE-269 状态）：PeersView 只读表格。上述用例失败。

## 5 问威胁建模

1. **数据**：对端身份（ID/租户/主体/类型）、远端卡片地址与凭据**引用**；无密钥值。
2. **调用方**：浏览器；服务端按 `peers.manage` 强制，远端登记还校验对端存在、租户一致、凭据可解析。
3. **信任边界**：服务端 `PeerIdentity`/`RemoteAgentRegistration` 校验（卡片地址 https 或 loopback）；
   卡片抓取有超时与大小上限；审计 `peer.register`/`peer.disable` 与远端登记动作。
4. **恶意输入**：前端只收集字段；渲染无 `v-html`。
5. **失败是否泄露信息**：固定文案或状态码。

## 范围外

- 对端授权（grant/revoke）表单、远端刷新/禁用按钮。
- 连接器申请审批、术语表导入之外的其余管理面。

## 证据

- `docs/evidence/SLICE-270-peers-forms.txt`
