# SLICE-092 A2A 模式互斥验证与迁移说明

状态: merged
依据: ADR-0014 切片段。

## 意图（要什么，不写怎么写）

SLICE-090 与 091 把 peer 模式与管理面做完了，但“两种模式不能混用”只有 CLI 层的散装用例，契约里没有 peer 记录与 token 文件的确切形状，迁移路径也没有文档。这一刀收口。

- 补库层负向验证：`build_a2a_app` 在缺 manifest、exposure 不符、身份源不唯一、存储缺失时拒绝构建。
- 补 CLI 负向验证：`--allow-unauthenticated` 与 peer 模式互斥；缺 peer 存储退出 2。
- 契约补全：`a2a.md` 加 peer 记录、授权记录与 token 文件格式。
- 写迁移说明：legacy 单 token 到 peer 模式的步骤、验证、回滚与排障。
- 实机演练同一 agent 的 legacy 与 peer 两个进程，旧 token 在 peer 模式下 401。

## 新增文件

- `tests/test_a2a_modes.py`
- `docs/guides/a2a-peer-migration.md`
- `docs/evidence/SLICE-092-a2a-peer-migration.txt`
- `docs/specs/SLICE-092-a2a-peer-migration.md`

## 修改文件

- `tests/test_cli_a2a_runtime.py`
- `docs/contracts/a2a.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
build_a2a_app 的拒绝条件（任一触发即以固定消息抛 ValueError）：
  peer 模式且 manifest 缺失或 exposure != "a2a"
  peer 模式且 oidc 与 peer_tokens 同时给出或同时缺失
  peer 模式且 peers 或 peer_grants 任一缺失

CLI 拒绝条件（退出 2）：
  peer 模式与 --auth-token-env（环境变量已设）或 --allow-unauthenticated 同时出现
  --peer-dir 与 --peer-db 同时给出或同时缺失
  --oidc-config 与 --peer-token-file 同时给出或同时缺失
  peer 模式缺 --manifest
```

契约补充的形状：

```text
PeerIdentity {peer_id, tenant, subject, kind, roles, enabled}
PeerGrant {peer_id, tenant, agent_id, actions: ["read","invoke"]}
token 文件: {"peer_id": "<64 hex sha256(token)>"}
--peer-dir 布局: <dir>/peers/<peer_id>.json, <dir>/grants/<peer_id>/<agent_id>.json
--peer-db 表: adk_peers, adk_peer_grants
```

## 完成判据（可执行）

- [x] 缺 manifest 被拒 -> `tests/test_a2a_modes.py::test_peer_mode_requires_manifest`
- [x] exposure 不符被拒 -> `::test_peer_mode_rejects_wrong_exposure`
- [x] 身份源不唯一被拒 -> `::test_peer_mode_requires_exactly_one_identity`
- [x] 存储缺失被拒 -> `::test_peer_mode_requires_both_stores`
- [x] 合法 peer 配置可构建 -> `::test_peer_mode_builds`
- [x] legacy 配置仍可构建 -> `::test_legacy_mode_builds`
- [x] allow-unauthenticated 与 peer 互斥 -> `tests/test_cli_a2a_runtime.py::test_peer_mode_rejects_allow_unauthenticated`
- [x] 缺 peer 存储退出 2 -> `::test_peer_mode_requires_store`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

这一刀是验证与文档收口，行为在 SLICE-090/091 已实现。红证据取自 peer 功能落地前的源码。

- [x] 反例 1：在 `6146450`（090 之前）跑新负向用例 -> `build_a2a_app` 不认识 peer 参数，用例以 `TypeError` 失败
- [x] 反例 2：在 `6146450` 跑 `serve-a2a --peer-dir` -> argparse 退出 2，互斥规则不存在
- [x] 反例 3：在 `d0b38b7`（091 之后、本切片之前）`grep "### 记录形状" docs/contracts/a2a.md` -> 为空，契约没有记录形状小节

## 契约（如涉及对外接口）

补 `docs/contracts/a2a.md` 的记录形状与存储布局，不改行为。

## 5 问威胁建模（10 分钟）

1. **数据**：迁移文档会点名 token 文件格式与存储路径，不能出现真实 token。
2. **调用方**：运维执行迁移，peer 调用方换 token。
3. **信任边界**：legacy 共享 token 到 per-peer 身份的切换。
4. **恶意输入最坏结果**：迁移时误把两种模式一起开（缓解：库层与 CLI 双重拒绝）；旧 token 继续可用（缓解：实机验证 401）；文档泄露真实凭据（缓解：只用占位符）。
5. **失败是否泄露信息**：拒绝消息只说明配置冲突，不回显 token。

## 范围外

- 自动改写调用方配置。
- token 签发工具与轮换计划。
- 网关层的灰度切流。

## 证据

- 反例红：`docs/evidence/SLICE-092-a2a-peer-migration.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，legacy 与 peer 两个进程、旧 token 401、新 token 200
