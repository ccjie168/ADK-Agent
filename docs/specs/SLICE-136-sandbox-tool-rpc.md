# SLICE-136 沙箱工具调用中介协议

状态: gated
依据: ADR-0024 第 3 条。worker 无网络，工具调用必须经类型化管道回到父进程执行。SLICE-129 到 135 只做了模型中介；工具调用被守卫拒绝，声明工具授权的 `sandboxed` 记录在加载处被拒。本切片落协议与父进程分派点，把工具实现接入留给下一片。

## 意图（要什么，不写怎么写）

1. worker 在加载工件后给 agent 树安装工具回调：任何工具调用都发 `tool` 帧，带调用 id、`tool_id` 与参数，等待父进程结果，不执行工件内工具函数。
2. 父进程新增 `tool` 帧处理：`tool_id` 必须在该次运行的 manifest 工具授权里，否则回 `tool_error`；授权通过时调用注入的工具执行器。
3. `ProcessAgentSandbox` 新增可选 `tools` 执行器（`async (manifest, tool_id, args) -> Mapping`）。没有执行器时任何工具调用返回 `tool_error`，错误码 `tool_mediation_unavailable`。
4. `AgentSandboxBackend.run` 增加可选 `manifest` 关键字；加载路径传入已发布 manifest，父进程据此校验授权。未传 manifest 时拒绝一切工具调用。
5. 只有执行器存在时，加载器才允许声明工具授权的 `sandboxed` 记录；否则维持拒绝（CLI 退出 1，控制台 409）。
6. 每次工具调用计入现有 wall clock 与 `max_model_calls` 同级的调用上限（新增 `max_tool_calls`，默认 100）。

## 数据形状

- 帧：worker -> 父 `{"type": "tool", "id": int, "tool_id": str, "args": object}`；
  父 -> worker `{"type": "tool_result", "id": int, "result": object}` 或
  `{"type": "tool_error", "id": int, "message": str, "code": str}`。
- `args` 必须是 JSON 可序列化对象；不可序列化时 worker 在发送前返回 `tool_error`。
- `manifest` 是 `AgentManifest`；父进程只读 `tool_grants` 的 `tool_id` 集合。

## 契约（先改）

- `docs/contracts/sandbox.md`：帧类型、授权判定、调用上限、无执行器语义。
- `docs/contracts/console.md` 与 `docs/contracts/cli.md`：工具授权 `sandboxed` 记录可加载的条件。
- `docs/contracts/trigger_service.md`：触发路径把 manifest 传给沙箱。

## 新增/修改文件

- 修改 `src/adk_agent/sandbox/agent.py`、`agent_channel.py`、`agent_process.py`、`agent_worker.py`
- 修改 `registry/loader.py`（按执行器能力决定是否允许工具授权）、`triggers_service.py`（传 manifest）
- 测试：`tests/sandbox/test_agent_tool_rpc.py`、`tests/test_registry_startup.py`、`tests/test_triggers_service.py`
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-136-sandbox-tool-rpc.txt`

## 完成判据（可执行）

- [x] 工具调用经父进程执行并返回结果 -> `test_tool_call_round_trips`
- [x] 未授权的 `tool_id` 被拒且执行器不被调用 -> `test_unauthorized_tool_is_refused`
- [x] 没有执行器时返回 `tool_mediation_unavailable` -> `test_tool_mediation_requires_executor`
- [x] 不可序列化的参数不发送 -> `test_unserializable_args_are_refused`
- [x] 工具调用超过上限时终止运行 -> `test_tool_call_limit`
- [x] 有执行器时声明工具授权的 `sandboxed` 记录可加载；无执行器仍拒绝 -> `test_loader_allows_tool_grants_with_executor`
- [x] 触发路径传入 manifest -> `test_trigger_passes_manifest_to_sandbox`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：当前 worker 没有工具帧，工具调用被网络/进程守卫拒绝 -> 期望 `test_tool_call_round_trips` 失败
- [x] 反例 2：当前 `run` 不接受 `manifest`，父进程无法校验授权 -> 期望 `test_unauthorized_tool_is_refused` 失败

## 5 问威胁建模（10 分钟）

1. **数据**：工具参数与结果、manifest 工具授权、调用上限计数。
2. **调用方**：工件代码（不可信）、父进程工具执行器。
3. **信任边界**：worker 到父进程；JSON 帧。
4. **恶意输入最坏结果**：工件伪造授权（缓解：父进程只信 manifest，不信子进程）；越权调用工具（缓解：`tool_id` 必须在 manifest 授权内）；超大参数拖垮父进程（缓解：沿用 32 MiB 帧上限与调用上限）；结果泄密（缓解：执行器由接入片按审批与租户策略实现）。
5. **失败是否泄露信息**：错误只带稳定 code 与短消息，不回显执行器内部错误详情。

残余风险：工具回调是进程内 Python 钩子，工件可用内省或 `gc` 摘除并让本地工具函数执行，
与 ADR-0024 第 9 条记录的 `ctypes` 绕过同级；生产前仍需容器或虚拟机层级。

## 范围外

- 工具执行器的实现（工具网关客户端、连接器、审批状态、`tool.call` 审计）在接入片。
- 沙箱内函数工具的本地执行仍被禁止；只有授权工具可经父进程调用。
- 工具结果的大小上限与脱敏细则。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-136-sandbox-tool-rpc.txt`
