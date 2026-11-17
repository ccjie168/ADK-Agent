# agent 沙箱 worker 协议

ADR-0024 的进程边界。父进程每次运行起一个子进程，把工件字节与输入送进去，拿回最终文本。

## 进程

- 命令：`<sys.executable> -I -m adk_agent.sandbox.agent_worker`，cwd 是本次运行的一次性临时目录，运行结束即删除。
  `-I` 不把 cwd 放进 `sys.path`，工件无法往后续运行的导入路径投放模块。
- 环境：POSIX 传空环境；Windows 只传 `SYSTEMROOT`、`TEMP`、`TMP`。
- 一次运行一个进程，结束即回收；不复用、不重试。

## 帧

- 4 字节大端长度加 UTF-8 JSON；最大 32 MiB，超过、截断或非 JSON 都算协议错误。
- 协议只走启动时的 stdout 句柄。子进程把 fd 1 重定向到 stderr，再单独保存一份原始 stdout 句柄写帧，所以工件的 `print` 不会污染协议。
  该句柄与工件同进程，工件若找到它并写入畸形帧，父进程按协议错误处理：先 kill 并回收子进程，再读取 stderr，stderr 收尾最多等 5 秒。
- stderr 由父进程并发读取，保留前 8 KiB 后继续读并丢弃，避免管道写满阻塞子进程。stderr 只用于诊断，可能包含宿主路径，只对可信调用方展示。

## 请求

```json
{
  "type": "run",
  "artifact": {"digest": "sha256:<hex>", "size": 1234, "entrypoint": "agent.py"},
  "data": "<base64 zip bytes>",
  "input": "hello",
  "limits": {
    "cpu_seconds": 10,
    "memory_mb": 1024,
    "open_files": 256,
    "file_bytes": 8388608,
    "processes": null
  }
}
```

输入不截断；调用方按服务入口的限制（当前 8000 字符）自行约束。

## 响应

- `{"type": "limits", "applied": {...}}`：内核读回的实际限制。`memory_mb` 以 MB 上报；POSIX 上才可能有内容，Windows 返回空对象。
- `{"type": "final", "text": "..."}`：最终响应文本。
- `{"type": "error", "kind": "violation|load|crash", "message": "<类名>: <短消息>"}`。
  - `violation`：守卫实际触发（按实例身份判定，工件伪造异常类不算），父进程抛 `SandboxViolation`。
  - `load`：工件解包、摘要、`exec` 或类型检查失败，父进程抛 `SandboxCrashed`。
  - `crash`：运行期异常，父进程抛 `SandboxCrashed`。

## 模型中介帧

子进程无网络，`adk_agent.build_model()` 在 worker 内被替换为代理模型。工件必须用它取模型；传入的 spec 只是标签，真正调用哪个模型由父进程决定。

- 子进程发 `{"type": "model", "id": <int>, "request": <LlmRequest JSON>}`。
- 父进程不信任请求内容：先校验成 `LlmRequest`，再在模型对象上强制 `model` 为注入模型的名字，
  清空 `config.http_options`、`config.cached_content`、`config.store`、`config.should_return_http_response`、
  `config.service_tier`、`config.labels`、`config.routing_config`、`config.model_selection_config`、
  `config.continuation_token`、`config.automatic_continuation`、`cache_config`、`cache_metadata`、
  `previous_interaction_id` 与 `live_connect_config`。snake_case 与 camelCase 别名都覆盖。
- `config.tools` 只允许 `function_declarations`（本地函数）。`mcp_servers`、`url_context`、`retrieval`、
  `file_search`、`google_search`、`code_execution` 等 provider 侧工具一律拒绝，因为它们绕过子进程守卫并由提供方执行。
- `contents` 任意层级与 `config.system_instruction` 里的 `file_data`/`File` 引用一律拒绝，父进程不按子进程给的 URI 取资源。
- 父进程在剩余墙钟内用注入的模型执行非流式调用，回
  `{"type": "model_result", "id": <int>, "responses": [<LlmResponse JSON>]}`，或
  `{"type": "model_error", "id": <int>, "message": "<异常类名>"}`。
- 父进程没有注入模型时回 `model_error`，消息是 `model mediation is not configured`，运行以 `SandboxCrashed` 结束。
- 单次运行最多 `max_model_calls`（默认 100）次模型调用，超过回 `model_error`，不执行模型。
- 响应超过帧上限或回包失败映射为 `SandboxCrashed`，无模型与超限两条分支同样适用，调用方不需要捕获传输层异常。
- 请求与响应都是普通帧，受 32 MiB 上限约束；id 由子进程递增分配，未知 id 的响应当作无主帧丢弃。
- 模型凭据只在父进程；子进程环境仍为空。工具调用不中转：工具里的外连会被守卫拒绝。

## 限制与平台差异

- POSIX：`RLIMIT_CPU`、`RLIMIT_AS`、`RLIMIT_NOFILE`、`RLIMIT_FSIZE`；`processes` 非空时设 `RLIMIT_NPROC`。
  `RLIMIT_AS` 以字节为单位设置，`memory_mb` 先乘 1024×1024；上报值是 `getrlimit` 读回值除以 1024×1024。
  `RLIMIT_NPROC` 按 uid 计数，同一服务账号下的并发运行共享该额度，默认关闭。
- Windows：不设置 `RLIMIT`，只保留脚本级网络守卫与环境清空。生产要求 POSIX，能力探测与启动参数在接入切片落地。
- 墙钟超时由父进程负责：写请求与读每一帧共用一个 deadline；超时后 `kill` 并 `wait`，抛 `SandboxTimeout`。
  POSIX 上子进程以独立会话启动（`start_new_session=True`），回收时用 `killpg` 杀掉整个进程组。
  回收是先等 5 秒、超时后 killpg 再等 5 秒，协议错误路径随后还要最多 5 秒收集 stderr，所以即使后代持有管道或用 `setsid` 逃出会话，单次运行的上界是 wall + 15 秒加进程启动开销。

## 网络与进程守卫

严格模式（agent worker 使用）拦截：

- `socket.getaddrinfo`、`socket.socket.connect`、`connect_ex`；
- `socket.socket` 构造 `AF_INET`、`AF_INET6`、`AF_UNIX`，以及 `_socket.socket` 按模块名直接构造；
- `os.system`、`os.popen`、`os.startfile`、`os.fork`/`forkpty`/`exec*`/`spawn*`、`subprocess.Popen`、
  `subprocess._fork_exec`、`_posixsubprocess.fork_exec`、`_winapi.CreateProcess`。

残余风险：工件仍可通过 `socket.socket.__bases__[0]` 等内省拿到原始 C 类型，或用 `ctypes` 直接调用 libc，绕过 Python 层守卫。这与 ADR-0024 第 9 条一致：v1 不是内核级隔离，开放给不受信网络调用方之前必须有容器或虚拟机层级。工件仍可读写宿主文件系统中服务账号有权限的路径；一次性 cwd 只堵导入路径投放，不是命名空间。
