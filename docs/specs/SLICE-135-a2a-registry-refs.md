# SLICE-135 A2A 的注册表启动

状态: gated
依据: ADR-0024 第 2、4 条与 ADR-0015。`console`、`serve`、`serve-many` 已能按 `--agent-ref` 启动并支持沙箱代理，`serve-a2a` 仍只接受本地 `--agent` 文件。本切片把 A2A 接到同一加载路径。

## 意图（要什么，不写怎么写）

1. `serve-a2a` 接受 `--agent-ref TENANT/ID@VERSION` 作为 `--agent` 的替代，二选一，重复给出退出 1。
2. `--agent-ref` 需要注册表（`--registry` 或 `--registry-url`）、工件字节来源（`--artifact-dir` 或 `ARTIFACT_URL`）与可信公钥（`--artifact-keys` 或 `ADK_ARTIFACT_KEYS`），缺任一项沿用现有退出 1 消息。
3. `serve-a2a` 支持 `--agent-sandbox` / `--allow-unsandboxed`；`sandboxed` 记录加载为沙箱代理，工具守卫不为代理安装。
4. peer 模式仍要求 `--manifest` 提供 agent card 身份；用 `--agent-ref` 时，加载出的 agent 名必须等于 manifest 的 `id`，否则退出 1。
5. `--agent` 的既有行为不变。

## 数据形状

- 复用 `_registry_agents(args)` 与 `load_registry_agents`，不新增类型。
- `serve-a2a` 只接受一个引用；多个引用退出 1。

## 契约（先改）

- `docs/contracts/cli.md`：`serve-a2a` 签名加入 `--agent-ref` 与沙箱 flag，写明互斥、依赖、peer 名称校验。

## 新增/修改文件

- 修改 `src/adk_agent/cli.py`
- 测试：`tests/test_cli_a2a_refs.py`
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-135-a2a-registry-refs.txt`

## 完成判据（可执行）

- [x] `serve-a2a --agent-ref` 用注册表工件启动，服务拿到对应 agent -> `test_serve_a2a_starts_from_ref`
- [x] `--agent` 与 `--agent-ref` 同时给退出 1 -> `test_agent_and_ref_conflict`
- [x] 多个 `--agent-ref` 退出 1 -> `test_single_ref_only`
- [x] peer 模式下引用 agent 名与 manifest id 不一致退出 1 -> `test_peer_ref_name_mismatch`
- [x] `sandboxed` 引用加载为代理且不安装工具守卫 -> `test_sandboxed_ref_uses_proxy`
- [x] `--agent` 既有启动行为不变 -> 既有 A2A 用例
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：`serve-a2a --agent-ref` 当前报未知参数并退出 2 -> 期望 `test_serve_a2a_starts_from_ref` 失败
- [x] 反例 2：`--agent` 为必填，无法省略 -> 期望 `test_agent_and_ref_conflict` 失败

## 5 问威胁建模（10 分钟）

1. **数据**：签名工件、manifest、A2A card 身份、peer token。
2. **调用方**：A2A 客户端与 peer。
3. **信任边界**：A2A 进程到工件代码；注册表记录到 agent card 身份。
4. **恶意输入最坏结果**：工件在 A2A 进程内执行（缓解：沙箱代理路径，与 SLICE-134 共用）；错误 manifest 冒充他人 card（缓解：名称必须等于 manifest id）；未信任工件（缓解：加载前签名校验）。
5. **失败是否泄露信息**：启动失败只打印现有消息并退出 1。

## 范围外

- 从注册表记录派生 peer manifest（仍需 `--manifest`）。
- 工具网关 RPC。
- A2A 运行时按请求选择版本。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-135-a2a-registry-refs.txt`
