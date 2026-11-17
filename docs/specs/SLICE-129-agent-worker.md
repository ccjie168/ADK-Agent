# SLICE-129 agent 沙箱 worker 与协议

状态: gated
依据: ADR-0024 第 2、3、4、6、8 条。先交付进程边界本身：一个工件在独立子进程里加载并跑一轮，无网络、清空环境、有资源上限、失败有类型。接入服务面与出口中介留给后续切片。

## 意图（要什么，不写怎么写）

1. 新增 `ProcessAgentSandbox`：每次 `run` 起一个子进程，把工件字节与输入送进去，返回最终文本。
2. 子进程内完成验摘要、解包、`exec`、建 Runner 与单轮运行。父进程只负责协议、超时与资源回收。
3. 子进程无网络：严格模式守卫拦 `getaddrinfo`、`connect`、`connect_ex`、`AF_INET`/`AF_INET6`/`AF_UNIX` 的 `socket.socket` 与 `_socket.socket` 构造，以及 `os.system`、`os.popen`、`fork`/`exec*`/`spawn*` 与 `subprocess.Popen`。绕过 Python 层的内省与 `ctypes` 属 ADR-0024 第 9 条的残余风险，写入契约。
4. 子进程环境清空，POSIX 上环境变量为空；Windows 只保留 `SYSTEMROOT`、`TEMP`、`TMP`。
5. POSIX 上设置 `RLIMIT_CPU`、`RLIMIT_AS`、`RLIMIT_NOFILE`、`RLIMIT_FSIZE`，可选 `RLIMIT_NPROC`；`memory_mb` 按字节换算，上报 `getrlimit` 读回值；平台不支持时跳过并如实上报。
6. 每次运行的 cwd 是父进程创建的一次性临时目录，结束删除；用 `-I` 启动，cwd 不进 `sys.path`。
7. 墙钟覆盖写请求、读帧与回收；协议错误先 kill 并回收子进程再读 stderr，失败有界。
6. 失败映射为 `SandboxViolation`、`SandboxTimeout`、`SandboxCrashed`，父进程总是杀掉并回收子进程。
7. 协议帧走独立句柄：工件对 fd 1 的输出重定向到 stderr，帧写到 `os.dup(1)` 保存的句柄，避免工件打印污染协议。
8. 收紧能力探针：注册值必须实现 `AgentSandboxBackend` 协议，`object()` 之类的占位不再算可用。
9. 本切片不接服务面，生产不注册后端，因此 `sandboxed` 仍然发不出、跑不起来；接入与真实模型出口在后续切片。

## 数据形状

`src/adk_agent/sandbox/agent.py`（扩展）：

- `SandboxResult(text: str)`，frozen dataclass。
- `AgentSandboxBackend`（`runtime_checkable` Protocol）：
  `async def run(artifact: AgentArtifact, data: bytes, input_text: str) -> SandboxResult`。
- `set_agent_sandbox_backend(backend)`：`None` 或带可调用、协程函数 `run` 的实现，否则 `TypeError`。
- `agent_sandbox_available()`：`_backend is not None`，注册时已校验 `run`。
- `require_execution_supported` 不变。

`src/adk_agent/sandbox/frames.py`（新文件）：

- `MAX_FRAME = 32 MiB`，`FrameError(ValueError)`。
- `write_frame(stream, payload)`、`read_frame(stream)`：4 字节大端长度加 UTF-8 JSON。
- `await write_frame_async(writer, payload)`、`await read_frame_async(reader)`：给 asyncio 流用。

`src/adk_agent/sandbox/agent_process.py`（新文件）：

- `AgentSandboxLimits`：`wall_seconds=30`、`cpu_seconds=10`、`memory_mb=1024`、`open_files=256`、`file_bytes=8 MiB`、`processes=None`。
- `ProcessAgentSandbox(limits=None)` 实现 `AgentSandboxBackend`。
- 启动命令：`[sys.executable, "-I", "-m", "adk_agent.sandbox.agent_worker"]`，cwd 是一次性临时目录；POSIX 传 `env={}`，Windows 传 `SYSTEMROOT/TEMP/TMP`。
- 墙钟超时由父进程负责；POSIX 以独立会话启动，超时后用 `killpg` 回收进程组；`wait()` 与 stderr 收尾各带 5 秒上限。
- stderr 并发读取，读到 EOF，只保留前 8 KiB，只用于诊断，不进结果。

`src/adk_agent/sandbox/agent_worker.py`（新文件）：

- 读一帧请求：`{"type": "run", "artifact": {...}, "data": <base64>, "input": str, "limits": {...}}`。
- 依次应用限制、安装网络守卫、清空环境，再 `load_artifact_agent(artifact, data)`（从 `registry/loader.py` 抽出的共用函数）。
- 用 `InMemorySessionService` 与 `Runner` 跑一轮，取最终响应文本。
- 回写 `{"type": "limits", "applied": {...}}`、`{"type": "final", "text": ...}` 或
  `{"type": "error", "kind": "violation|load|crash", "message": <类名或短消息>}`。
- 任何路径都不得把环境变量或密钥写进帧。

`src/adk_agent/registry/loader.py`（重构）：

- 抽出 `load_artifact_agent(artifact, data) -> Any`：验大小与摘要、解包、条目检查、`exec`、类型与名字检查。
- `InProcessArtifactLoader.load` 只负责取字节并调用它，行为不变。

## 契约（先改）

- `docs/contracts/sandbox.md`（新文件）：worker 协议帧、资源上限字段、错误种类与映射、平台差异。
- `docs/contracts/README.md`：加一行。
- 不改 `manifest.schema.json` 与发布/加载接口。

## 新增文件

- `src/adk_agent/sandbox/frames.py`
- `src/adk_agent/sandbox/agent_process.py`
- `src/adk_agent/sandbox/agent_worker.py`
- `tests/sandbox/test_agent_frames.py`
- `tests/sandbox/test_agent_process.py`
- `docs/contracts/sandbox.md`
- `docs/evidence/SLICE-129-agent-worker.txt`

## 修改文件

- `src/adk_agent/sandbox/agent.py`、`src/adk_agent/sandbox/errors.py`（新增 `SandboxCrashed`）
- `src/adk_agent/registry/loader.py`
- `tests/registry/test_execution_tier_boundary.py`（后端桩改成实现协议的类）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 帧往返：写读一致，超长帧抛 `FrameError` -> `tests/sandbox/test_agent_frames.py`
- [x] 正常工件返回最终文本 -> `tests/sandbox/test_agent_process.py::test_run_returns_final_text`
- [x] 子进程环境已清空（POSIX 为空；Windows 只含允许项） -> `::test_environment_is_cleared`
- [x] 工件尝试联网抛 `SandboxViolation` -> `::test_network_access_is_denied`
- [x] 超出墙钟抛 `SandboxTimeout`，子进程被回收 -> `::test_wall_clock_timeout`
- [x] 加载期异常抛 `SandboxCrashed` -> `::test_load_failure_is_a_crash`
- [x] 字节与摘要不符抛 `SandboxCrashed` -> `::test_digest_mismatch_is_rejected`
- [x] 子进程上报的限制与请求一致（POSIX，读回值） -> `::test_limits_are_reported`
- [x] 工件打印不污染协议，stderr 有输出 -> `::test_artifact_stdout_is_redirected`
- [x] UDP 出口被拒 -> `::test_udp_egress_is_denied`
- [x] 直接构造 `_socket.socket` 被拒 -> `::test_raw_socket_module_is_denied`
- [x] `AF_UNIX` 套接字被拒（POSIX） -> `::test_unix_sockets_are_denied`
- [x] 子进程创建被拒 -> `::test_process_creation_is_denied`
- [x] 低层 `_fork_exec` 被拒（POSIX） -> `::test_low_level_fork_exec_is_denied`
- [x] 直接调用 `_posixsubprocess.fork_exec` 被拒（POSIX） -> `::test_posixsubprocess_fork_exec_is_denied`
- [x] 后代持有管道时运行仍有界结束（POSIX） -> `::test_descendant_holding_pipes_does_not_hang`
- [x] 工件伪造 `SandboxViolation` 仍归为崩溃 -> `::test_artifact_cannot_forge_a_violation`
- [x] 运行目录是一次性临时目录且被删除 -> `::test_runs_in_a_removed_temp_directory`
- [x] 畸形帧且子进程存活时有界失败 -> `::test_malformed_frame_does_not_hang`
- [x] `_clear_env` 单独移除密钥 -> `::test_clear_env_removes_secrets`
- [x] 非法 limits 帧值抛 `SandboxCrashed` -> `::test_invalid_limit_values_are_rejected`
- [x] `set_agent_sandbox_backend(object())` 抛 `TypeError`，协议桩算可用 -> `tests/sandbox/test_agent_process.py::test_backend_must_implement_the_protocol` 与 `tests/registry/test_execution_tier_boundary.py`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：子进程能建立外连 -> 期望 `::test_network_access_is_denied` 失败
- [x] 反例 2：超时后父进程不杀子进程 -> 期望 `::test_wall_clock_timeout` 失败
- [x] 反例 3：占位后端对象被当成可用 -> 期望 `tests/sandbox/test_agent_process.py::test_backend_must_implement_the_protocol` 与 `tests/registry/test_execution_tier_boundary.py::test_a_placeholder_backend_does_not_count` 失败
- [x] 反例 4：工件打印混入协议帧 -> 期望 `::test_artifact_stdout_is_redirected` 失败
- [x] 反例 5：`memory_mb` 未按字节换算 -> 期望 POSIX 上所有正常用例与 `::test_limits_are_reported` 失败（验证代理在 Linux 容器复现）
- [x] 反例 6：畸形帧后先等 stderr 再回收 -> 期望 `::test_malformed_frame_does_not_hang` 挂起或超时

红态记录: 见证据文件。

## 5 问威胁建模（10 分钟）

1. **数据**：工件 zip 字节、摘要、输入文本、最终文本、资源上限、子进程 stderr。
2. **调用方**：`ProcessAgentSandbox` 由可信服务调用；本切片只有测试调用，后续由控制台与触发服务接入。
3. **信任边界**：父进程到子进程的协议；子进程内到操作系统（socket、环境、文件系统、进程表）。
4. **恶意输入最坏结果**：读平台环境变量（缓解：清空 env，工件只能看到白名单）；外连或逃逸出口（缓解：socket 守卫，后续切片再加父进程中转）；打印污染协议（缓解：帧走独立句柄，fd 1 重定向 stderr）；无限运行或耗尽资源（缓解：墙钟、CPU、地址空间、文件大小上限，父进程无条件回收）；fork 炸弹（缓解：可选 `RLIMIT_NPROC`，按 uid 计数的语义写进契约；v1 不默认开启以免影响宿主）；协议大帧耗尽内存（缓解：32 MiB 上限）；子进程崩溃后僵尸进程（缓解：`kill` 后 `await wait`）。
5. **失败是否泄露信息**：错误只带异常类名与截断后的 stderr，不含环境变量、密钥或路径。stderr 截断到 8 KiB。

## 范围外

- 模型与工具出口中介（SLICE-130）。本切片的工件必须自带不联网的模型实现，真实模型调用在 SLICE-130 之后才可用。
- 控制台、触发服务与 A2A 的接入，以及发布默认层级翻转（SLICE-131）。
- 内核级隔离、容器、seccomp、命名空间。
- Windows 上的 `RLIMIT` 等价物（作业对象）；Windows 只保证脚本级网络守卫与环境清空。
- 每租户系统用户。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-129-agent-worker.txt`
