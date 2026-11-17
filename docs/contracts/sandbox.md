# agent 沙箱 worker 协议

ADR-0024 的进程边界。父进程每次运行起一个子进程，把工件字节与输入送进去，拿回最终文本。

## 进程

- 命令：`<sys.executable> -E -s -m adk_agent.sandbox.agent_worker`。
- 环境：POSIX 传空环境；Windows 只传 `SYSTEMROOT`、`TEMP`、`TMP`。
- 一次运行一个进程，结束即回收；不复用、不重试。

## 帧

- 4 字节大端长度加 UTF-8 JSON；最大 32 MiB，超过、截断或非 JSON 都算协议错误。
- 协议只走启动时的 stdout 句柄。子进程把 fd 1 重定向到 stderr，再单独保存一份原始 stdout 句柄写帧，所以工件的 `print` 不会污染协议。
- stderr 由父进程并发读取，最多保留 8 KiB，只用于诊断。

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

## 响应

- `{"type": "limits", "applied": {"cpu_seconds": 10, ...}}`：实际生效的限制。POSIX 上才可能有内容；Windows 返回空对象。
- `{"type": "final", "text": "..."}`：最终响应文本。
- `{"type": "error", "kind": "violation|load|crash", "message": "<类名>: <短消息>"}`。
  - `violation`：网络守卫或其它沙箱守卫拒绝，父进程抛 `SandboxViolation`。
  - `load`：工件解包、摘要、`exec` 或类型检查失败，父进程抛 `SandboxCrashed`。
  - `crash`：运行期异常，父进程抛 `SandboxCrashed`。

## 限制与平台差异

- POSIX：设置 `RLIMIT_CPU`、`RLIMIT_AS`、`RLIMIT_NOFILE`、`RLIMIT_FSIZE`；`processes` 非空时设 `RLIMIT_NPROC`。
  `RLIMIT_NPROC` 按 uid 计数，同一服务账号下的并发运行共享该额度，默认关闭。
- Windows：不设置 `RLIMIT`，只保留脚本级网络守卫与环境清空。生产要求 POSIX，能力探测与启动参数在接入切片落地。
- 墙钟超时由父进程负责，超时后 `kill` 并 `wait`，抛 `SandboxTimeout`。

## 边界

- 子进程无网络：socket 的 `getaddrinfo`、`connect`、`connect_ex` 被替换，任何新连接抛 `SandboxViolation`。事件循环在安装守卫前创建，避免 Windows 的 loopback socketpair 被误伤。
- 环境清空发生在安装守卫之后、加载工件之前。
- 工件仍然可以通过文件系统访问宿主文件；v1 不做文件系统命名空间，见 ADR-0024 第 9 条。
- 本切片不注册后端，发布与加载仍把 `sandboxed` 当作不可用。
