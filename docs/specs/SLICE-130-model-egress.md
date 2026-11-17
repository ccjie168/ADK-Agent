# SLICE-130 沙箱模型出口中介

状态: gated
依据: ADR-0024 第 3 条。子进程无网络，模型调用改经父进程中转；父进程持模型凭据并按平台策略调用。工具出口保持拒绝，工具网关 RPC 留给接入切片。

## 意图（要什么，不写怎么写）

1. 沙箱子进程里的 `build_model()` 返回一个代理模型，它把 `LlmRequest` 发到父进程并等待 `LlmResponse`。
2. 真正的模型调用发生在父进程，凭据、模型通道与白名单都在可信侧；子进程环境仍然为空。
3. 协议新增双向帧：子进程发 `model`，父进程回 `model_result` 或 `model_error`，带请求 id。
4. 父进程为每次 `run` 注入一个模型实例（默认没有），没有模型时模型帧返回错误，运行以 `SandboxCrashed` 结束。
5. 工件自行构造的字符串模型仍然被网络守卫拒绝；契约要求沙箱工件用 `build_model()` 取模型。
6. 工具调用不中转。声明了工具授权的工件可以运行，但工具内的外连会被守卫拒绝；工具网关 RPC 在接入切片做。

## 数据形状

`src/adk_agent/sandbox/agent_channel.py`（新文件）：

- `SandboxModelError(RuntimeError)`。
- `SandboxChannel(reader, writer)`：
  - `start()` 在事件循环里启动读帧任务。
  - `async call_model(request: dict) -> list[dict]`：分配 id，写 `{"type": "model", "id": int, "request": ...}`，等待对应响应。
  - 读帧循环把 `model_result` / `model_error` 按 id 交给等待方；EOF 或协议错误让所有等待方抛 `SandboxModelError`。
  - `close()` 取消读帧任务。
- `set_channel(channel)` / `channel()`：worker 在加载工件前设置。
- `SandboxModel(BaseLlm)`：`generate_content_async` 调 `channel().call_model(llm_request.model_dump(mode="json"))`，逐条产出 `LlmResponse.model_validate(...)`。
- 父进程侧 `_sanitize_model_request`：先校验，再强制 `model`，清空 egress 字段，`config.tools` 只留
  `function_declarations`，`contents` 任意层级与 `system_instruction` 的文件引用一律拒绝。

`src/adk_agent/sandbox/agent_worker.py`（修改）：

- 读请求后创建 `SandboxChannel(sys.stdin.buffer, out)` 并 `set_channel`。
- 加载工件前替换 `adk_agent.build_model` 与 `adk_agent.models.build_model` 为返回 `SandboxModel(model=...)` 的工厂，忽略传入的 spec。
- `_run` 里 `channel.start()` 并在结束时 `channel.close()`。

`src/adk_agent/sandbox/agent_process.py`（修改）：

- `ProcessAgentSandbox(limits=None, model=None)`，`model` 是 `BaseLlm | None`，由可信调用方注入。
- `AgentSandboxLimits.max_model_calls` 默认 100，按运行计数。
- 帧循环处理 `model`：校验 id，还原 `LlmRequest`，在剩余墙钟内调用 `model.generate_content_async(..., stream=False)`，
  回写 `model_result` 或 `model_error`。模型错误不杀进程，由工件决定如何失败。
- 写完运行请求后不再关闭 stdin，留给模型响应；进程收尾时再关。
- 没有注入模型时回 `model_error("model mediation is not configured")`。

## 契约（先改）

- `docs/contracts/sandbox.md`：新增 `model` / `model_result` / `model_error` 帧与 id 规则；说明父进程持凭据、子进程只能通过 `build_model()` 取模型；工具出口仍拒绝。

## 新增文件

- `src/adk_agent/sandbox/agent_channel.py`
- `tests/sandbox/test_agent_channel.py`
- `docs/evidence/SLICE-130-model-egress.txt`

## 修改文件

- `src/adk_agent/sandbox/agent_worker.py`、`src/adk_agent/sandbox/agent_process.py`
- `docs/contracts/sandbox.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- `tests/sandbox/test_agent_process.py`

## 完成判据（可执行）

- [x] 工件用 `build_model()` 时最终文本来自父进程注入的模型 -> `tests/sandbox/test_agent_process.py::test_model_calls_are_mediated`
- [x] 父进程模型收到原始 `LlmRequest`（含用户输入） -> 同上用例检查调用记录
- [x] 工件传入的 spec 不影响结果，模型由父进程决定 -> `::test_model_spec_is_ignored`
- [x] 未注入模型时运行以 `SandboxCrashed` 结束 -> `::test_model_mediation_requires_a_parent_model`
- [x] 父进程模型抛错时子进程收到 `model_error` 并以 `SandboxCrashed` 结束 -> `::test_model_errors_are_returned`
- [x] 子进程塞入的 `http_options` 与模型名被父进程剥离/覆盖 -> `::test_model_request_is_sanitized`
- [x] 模型错误不向调用方泄漏原始异常文本 -> `::test_model_errors_do_not_leak_detail`
- [x] 超限模型响应映射为 `SandboxCrashed` -> `::test_oversized_model_response_is_crashed`
- [x] 单次运行的模型调用次数受限 -> `::test_model_call_limit_is_enforced`
- [x] camelCase 别名与 `cache_config.create_http_options` 被剥离 -> `::test_model_aliases_and_cache_options_are_stripped`
- [x] `file_data` 引用被拒绝 -> `::test_model_file_references_are_rejected`
- [x] 无模型与超限分支的回包失败也映射为 `SandboxCrashed` -> `::test_reply_failures_are_crashed`
- [x] provider 侧工具被拒绝，本地 function declarations 保留 -> `::test_provider_tools_are_rejected` 与 `::test_local_function_tools_are_allowed`
- [x] 嵌套 `function_response` 与 `system_instruction` 的文件引用被拒绝 -> `::test_nested_file_references_are_rejected`
- [x] continuation 与 service tier 字段被清空 -> `::test_continuation_fields_are_cleared`
- [x] 子进程环境仍为空（模型调用不在子进程） -> `::test_model_run_keeps_the_worker_env_empty`
- [x] 通道帧往返与 id 分发 -> `tests/sandbox/test_agent_channel.py`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：子进程直接调用真实模型（无中介）-> 期望 `::test_model_calls_are_mediated` 失败
- [x] 反例 2：未注入模型仍能运行 -> 期望 `::test_model_mediation_requires_a_parent_model` 失败
- [x] 反例 3：通道不按 id 分发 -> 期望 `tests/sandbox/test_agent_channel.py` 分发用例失败

红态记录: 见证据文件。

## 5 问威胁建模（10 分钟）

1. **数据**：`LlmRequest` 与 `LlmResponse` 的 JSON、请求 id、模型名、父进程凭据。
2. **调用方**：沙箱工件通过 `build_model()` 与 ADK 的模型接口；父进程由可信服务注入模型。
3. **信任边界**：子进程到父进程的模型帧；父进程到模型提供方。
4. **恶意输入最坏结果**：工件用模型帧放大父进程内存（缓解：单帧 32 MiB 上限，响应逐条转发）；伪造 id 或乱序（缓解：未知 id 丢弃并让等待方超时/报错）；借模型通道窃取凭据（缓解：凭据只在父进程，帧里只有请求与响应）；用 `model_error` 探测提供方细节（缓解：只回异常类名）；绕过代理直接联网（缓解：网络守卫拒绝，工件必须用 `build_model()`）。
5. **失败是否泄露信息**：`model_error` 只含异常类名；响应内容按模型输出原样返回给工件，属于工件自己的数据。

## 范围外

- 工具网关 RPC 与工具外连中介（接入切片）。
- 流式模型响应；v1 统一按非流式取回，再逐条交给 ADK。
- 模型选择策略与用量计费；父进程注入什么模型就调用什么。
- 平台门槛（POSIX、降 uid、网络命名空间）与 `sandboxed` 的执行路由（接入切片）。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-130-model-egress.txt`
