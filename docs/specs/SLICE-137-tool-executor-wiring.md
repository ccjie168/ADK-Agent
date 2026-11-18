# SLICE-137 工具执行器接入

状态: gated
依据: ADR-0024 第 3 条。SLICE-136 已交付工具帧协议与父进程分派点。本切片实现执行器：把授权工具调用发到工具网关，按运行主体的租户、授权与审批状态执行，并写 `tool.call` 审计。

## 意图（要什么，不写怎么写）

1. 新增工具网关客户端 `tools/client.py`：`POST /v1/invoke`，请求形状 `ToolGatewayRequest`，支持 Bearer token、超时与错误映射。
2. 父进程执行器由网关客户端构造：`async (manifest, tool_id, args, invocation) -> Mapping`，`invocation` 带本次运行的主体与 agent_ref。
3. 运行主体来源：`AgentRuntime` 在每次运行期间把当前 `Invocation` 放进 contextvar；`SandboxAgent` 读取并传给 `backend.run(..., invocation=...)`。没有当前主体时执行器拒绝（`tool_principal_unavailable`）。
4. CLI 新增 `--tool-gateway-url` 与 `--tool-gateway-token-env`，作用于 `console`、`serve`、`serve-many`、`serve-a2a`；与 `--agent-sandbox` 同用时构造带执行器的 `ProcessAgentSandbox`。
5. 带工具授权的 `sandboxed` 记录在配置了网关时可加载；未配置时维持现有拒绝。
6. 审批：`requires_approval` 的工具交给网关按现有规则拒绝（`approval_required`），本切片不新增审批路径。
7. 触发路径暂不接执行器，继续拒绝工具授权记录。

## 数据形状

- `ToolGatewayClient.invoke(invocation, tool_id, args, grants) -> Any`；403 映射 `ToolDenied`，其余非 200、5xx、网络与坏响应映射 `ToolGatewayError`。
- 复用 `core.context` 的 `current_invocation()`：`AgentRuntime._run` 与 `AuditedRunner` 都会设置，覆盖控制台与 MCP/A2A 路径。
- `AgentSandboxBackend.run` 增加可选关键字 `invocation`；协议仍只按 manifest 授权。

## 契约（先改）

- `docs/contracts/tool_gateway.md`（或 `tools.md`）：客户端调用形状、鉴权与错误映射。
- `docs/contracts/sandbox.md`：执行器主体来源与拒绝码。
- `docs/contracts/cli.md`：四个命令的新 flag。

## 完成判据（可执行）

- [x] 客户端按 `ToolGatewayRequest` 调用并解析结果 -> `tests/tools/test_client.py`
- [x] 运行期间 contextvar 有 principal，结束后清空 -> `tests/runtime/test_execution.py`
- [x] 代理把 principal 传给后端 -> `tests/sandbox/test_agent_proxy.py`
- [x] 执行器在缺 invocation 时拒绝 -> `tests/tools/test_gateway_executor.py`
- [x] 后端带执行器时工具授权记录可加载，否则拒绝 -> `tests/test_registry_startup.py`
- [x] CLI flag 解析与后端构造 -> `tests/test_cli_sandbox_adapters.py`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（实现前跑红）

- [x] 反例 1：当前没有工具网关客户端 -> `tests/tools/test_client.py` 收集失败
- [x] 反例 2：当前代理不传 principal -> `test_sandbox_agent_passes_the_current_invocation` 失败

## 5 问威胁建模

1. **数据**：工具参数与结果、principal、网关 token。
2. **调用方**：工件（不可信）、父进程、工具网关。
3. **信任边界**：父进程到网关；contextvar 只在父进程可信侧写入。
4. **恶意输入最坏结果**：冒充他租户（缓解：principal 来自运行主体，网关绑定 token）；绕过审批（缓解：网关既有 `approval_required`）；token 泄露进子进程（缓解：worker 环境清空，token 只在父进程客户端）。
5. **失败是否泄露信息**：错误只回稳定 code。

## 范围外

- 触发路径接执行器。
- 新的审批交互与通知。
- 网关侧多目标路由。

## 证据

- `docs/evidence/SLICE-137-tool-executor-wiring.txt`
