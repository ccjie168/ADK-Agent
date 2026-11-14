# SLICE-091 peer 与授权管理面

状态: merged
依据: ADR-0014 切片段。

## 意图（要什么，不写怎么写）

SLICE-090 让 A2A 按 peer 身份授权，但 peer 与授权只能手改文件。这一刀给运维控制台与命令入口。

- 控制台新增五个接口：列 peer 与授权、注册 peer、停用 peer、写入授权、撤销授权。
- 控制台新增 Peer 面板，复用现有租户下拉。
- CLI `adk-agent peers list|register|disable|grant|revoke`。
- 管理操作写审计：`peer.register`、`peer.disable`、`peer.grant`、`peer.revoke`。
- 审计视图不改代码：`peer.call` 与 `agent.run` 已经在同一份共享审计里，本切片补一条断言证明它会出现在 `/api/audit`。

## 新增文件

- `tests/test_console_peers.py`
- `tests/test_cli_peers.py`
- `docs/evidence/SLICE-091-peer-management.txt`
- `docs/specs/SLICE-091-peer-management.md`

## 修改文件

- `src/adk_agent/core/ports.py`（`PeerGrantStore.delete`）
- `src/adk_agent/registry/peer_grants.py`、`src/adk_agent/registry/peer_grants_postgres.py`
- `src/adk_agent/console.py`（五个接口、Peer 面板、`--peer-dir`/`--peer-db`）
- `src/adk_agent/cli.py`（`peers` 子命令与 `console` 的 peer 存储参数）
- `tests/registry/test_peer_stores.py`（撤销用例）
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GET    /api/peers?tenant=T          -> [{"peer": PeerIdentity, "grants": [PeerGrant]}]
POST   /api/peers                   -> PeerIdentity
        body: {peer_id, tenant, subject, kind?, roles?}
POST   /api/peers/{id}/disable      -> PeerIdentity
POST   /api/peers/{id}/grants       -> PeerGrant
        body: {agent_id, actions}
DELETE /api/peers/{id}/grants/{agent_id} -> {"revoked": bool}

CLI:
  peers list [--tenant T] [--peer-dir DIR | --peer-db URL]
  peers register --id ID --tenant T [--subject S] [--kind K] [--roles A,B]
  peers disable --id ID
  peers grant --id ID --agent AGENT --actions read,invoke
  peers revoke --id ID --agent AGENT
```

规则：

- 读：非 admin 只看自己租户；admin 可按 `tenant` 取某一个租户，缺省返回全部。
- 写：只有 admin。非 admin 403 `forbidden`；跨租户 403 `tenant_forbidden`。
- 已存在 peer 改 `tenant` 返回 409 `peer_tenant_immutable`，避免授权挂到错误租户。
- grant 的 `tenant` 取 peer 的租户，请求体不接受 `tenant`；peer 不存在 404 `peer_not_found`；`actions` 为空或含未知值 400 `invalid_grant`。
- 停用幂等；撤销不存在的授权返回 `{"revoked": false}`，不报错。
- 未配置 peer 存储时 404 `peers_not_configured`；存储失败 503 `peer_store_unavailable`。
- 审计：`peer.register` 与 `peer.disable` 的 `target` 是 peer id；`peer.grant` 与 `peer.revoke` 的 `target` 是 `<peer_id>/<agent_id>`。tenant 用调用方租户。

## 完成判据（可执行）

- [x] 列出 peer 与其授权，按 peer_id 排序 -> `tests/test_console_peers.py::test_list_peers_with_grants`
- [x] 非 admin 只看自己租户 -> `::test_tenant_visibility`
- [x] 注册写 `peer.register` 审计 -> `::test_register_audited`
- [x] 改租户被拒 -> `::test_tenant_immutable`
- [x] 停用幂等并写审计 -> `::test_disable_idempotent`
- [x] 写入与撤销授权 -> `::test_grant_and_revoke`
- [x] 授权租户跟随 peer -> `::test_grant_tenant_follows_peer`
- [x] 未配置存储 404 -> `::test_not_configured`
- [x] `peer.call` 出现在 `/api/audit` -> `::test_peer_call_in_audit_view`
- [x] CLI 文件流程 -> `tests/test_cli_peers.py::test_cli_file_flow`
- [x] CLI 撤销不存在的授权成功 -> `::test_cli_revoke_missing`
- [x] CLI 未知动作退出 1 -> `::test_cli_bad_action_exits`
- [x] 存储 delete 幂等 -> `tests/registry/test_peer_stores.py::test_grant_delete`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`GET /api/peers` -> 当前 404（路由不存在）
- [x] 反例 2：`adk-agent peers list --peer-dir X` -> 当前 argparse 退出 2
- [x] 反例 3：`PeerGrantStore` 没有 `delete` -> 当前 `AttributeError`

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：peer 标识、租户、subject、角色、agent 动作授权。
2. **调用方**：控制台 admin、CLI 操作者。
3. **信任边界**：浏览器表单到 peer 存储；CLI 到文件或 Postgres。
4. **恶意输入最坏结果**：非 admin 给自己发授权（缓解：写接口只允许 admin）；跨租户改 peer（缓解：租户检查与不可变租户）；给不存在的 agent 发授权（缓解：授权只按 peer 写入，agent 是否存在由调用侧校验；本切片记录这是已知缺口）；伪造审计（缓解：审计由服务端写，target 与 tenant 由服务端拼）。
5. **失败是否泄露信息**：错误只回固定码，不回显 subject 之外的凭据；peer 记录本身不含 token。

## 范围外

- token 签发、轮换与吊销 UI。
- OIDC 配置管理。
- 批量导入与导出。
- 校验授权里的 agent 是否已发布（留给后续，与工具授权一致）。

## 证据

- 反例红：`docs/evidence/SLICE-091-peer-management.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，控制台接口与 CLI 对同一个文件存储读写
