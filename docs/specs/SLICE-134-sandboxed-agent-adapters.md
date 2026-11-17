# SLICE-134 控制台与 MCP 的沙箱执行适配

状态: gated
依据: ADR-0024 第 2、4、5 条。SLICE-128 到 131 已交付执行层级、子进程 worker、模型出口中介与触发路径。控制台与 MCP 仍拒绝 `sandboxed`，注册后端后也不得让它们回落到进程内执行。本切片把 `--agent-ref` 与控制台按需加载接到沙箱。

## 意图（要什么，不写怎么写）

1. `console`、`serve`、`serve-many` 新增 `--agent-sandbox`：注册 `ProcessAgentSandbox(model=build_model())` 为全局后端；非 POSIX 默认退出 1，`--allow-unsandboxed` 才降级运行。
2. `load_agent` 遇到 `sandboxed` 记录返回沙箱代理 agent，而不是执行工件字节；进程内 loader 不再被调用。
3. 控制台 `POST /api/registry/load` 对 `sandboxed` 记录返回同类代理，仍受 `--max-loaded-agents` 与同名冲突约束。
4. 沙箱代理每次调用起一个新的子进程，模型调用经受控通道；子进程不持有凭据。
5. 声明工具授权的 `sandboxed` 记录在加载时被拒绝（工具网关 RPC 未实现），控制台按需加载返回 409 `tool_mediation_unavailable`。
6. 未注册后端时行为不变：`sandboxed` 仍在加载处被拒。
7. 沙箱代理没有会话记忆：每次调用独立，控制台会话只保存消息，不保存工件内状态。

## 数据形状

- `SandboxAgent(BaseAgent)` 持有 `AgentArtifact`、工件字节与 `AgentSandboxBackend`；`_run_async_impl` 取本次用户文本，调用 `backend.run(artifact, data, text)`，产出一个模型 `Event`。
- 输入取 `InvocationContext.user_content` 的第一个文本 part；没有文本时传空串。
- 加载入口 `load_agent` 与 `load_sandbox_agent(record, store=...)` 共用同一分支判断，避免控制台绕过。

## 契约（先改）

- `docs/contracts/cli.md`：三个命令的 `--agent-sandbox`、`--allow-unsandboxed` 与平台门槛。
- `docs/contracts/sandbox.md`：沙箱代理的调用语义、无会话记忆、工具授权拒绝。
- `docs/contracts/console.md`：`POST /api/registry/load` 对 `sandboxed` 的行为与 409 `tool_mediation_unavailable`。

## 新增/修改文件

- 新增 `src/adk_agent/sandbox/proxy.py`
- 修改 `src/adk_agent/sandbox/agent.py`、`registry/loader.py`、`console.py`、`cli.py`
- 测试：`tests/sandbox/test_agent_proxy.py`、`tests/test_registry_loader.py`、`tests/test_console_on_demand.py`、`tests/test_cli_sandbox_adapters.py`
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-134-sandboxed-agent-adapters.txt`

## 完成判据（可执行）

- [ ] 注册后端时 `load_agent` 对 `sandboxed` 返回代理且不执行工件 -> `test_load_agent_returns_sandbox_proxy`
- [ ] 代理调用后端并把返回文本作为模型事件 -> `test_sandbox_agent_runs_backend`
- [ ] 未注册后端时 `load_agent` 仍抛 `AgentSandboxUnavailable` -> 既有用例
- [ ] 声明工具授权的 `sandboxed` 记录被拒 -> `test_sandboxed_with_tool_grants_is_refused`
- [ ] 控制台按需加载返回代理；带工具授权返回 409 `tool_mediation_unavailable` -> `tests/test_console_on_demand.py`
- [ ] `console`/`serve`/`serve-many` 接受 `--agent-sandbox`，非 POSIX 未加覆盖退出 1 -> `tests/test_cli_sandbox_adapters.py`
- [ ] 沙箱代理不调用 `InProcessArtifactLoader` / 不 `exec` 工件 -> 代理用例用会抛错的 loader 验证
- [ ] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [ ] 反例 1：注册后端后 `load_agent` 仍执行工件 -> 期望 `test_load_agent_returns_sandbox_proxy` 失败
- [ ] 反例 2：控制台按需加载 `sandboxed` 记录仍调用进程内 loader -> 期望 `test_on_demand_sandboxed_uses_proxy` 失败

## 5 问威胁建模（10 分钟）

1. **数据**：签名工件字节、清单、工件内代码、子进程模型调用。
2. **调用方**：控制台会话、MCP 客户端、注册表引用。
3. **信任边界**：控制台/MCP 进程到工件代码；父进程到子进程。
4. **恶意输入最坏结果**：工件在控制台进程内执行（缓解：代理路径，进程内 loader 不被调用）；子进程偷凭据（缓解：SLICE-130 的模型中介与清理后的环境）；工件调用工具出网（缓解：守卫拒绝，声明工具授权的记录直接不加载）；无限制资源消耗（缓解：ProcessAgentSandbox 的 RLIMIT 与 wall clock）。
5. **失败是否泄露信息**：加载失败只返回既有错误码；沙箱运行错误沿用触发路径的稳定 500 映射。

## 范围外

- 工具网关 RPC 与沙箱内工具调用。
- A2A 的 `--agent-ref`（`serve-a2a` 目前只接受 `--agent` 文件，接入注册表另立切片）。
- 沙箱内会话持久化。
- 平台构建密钥校验与 publish 默认层级翻转。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-134-sandboxed-agent-adapters.txt`
