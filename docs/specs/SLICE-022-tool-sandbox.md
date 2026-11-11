# SLICE-022 工具沙箱（M2-4）

状态: gated
依据: ADR-0002 第 5、6 条

## 意图（要什么，不写怎么写）

给本地函数工具加上执行边界。

- 每次工具调用有超时。超时后进程被终止，调用返回 `SandboxTimeout`。
- POSIX 上用子进程执行工具，设置 CPU 和内存上限。
- 子进程默认没有网络。`allowed_hosts` 可以放行指定主机。
- 子进程清空环境变量。工具读不到模型 API Key。
- HTTP 工具源有可选出口白名单。MCP URL 和 OpenAPI `servers` 在建 agent 时检查。
- 控制台和 ADK 工具循环用同一套沙箱包装。
- Windows 没有可用的进程隔离时退化为线程超时。网络和资源隔离不可用，这一点写清楚。
- 这一刀收口 M2。越权工具被拒并留痕，沙箱对本地工具和 HTTP 工具源都生效。

## 新增文件

- `src/adk_agent/sandbox/__init__.py`
- `src/adk_agent/sandbox/policy.py`
- `src/adk_agent/sandbox/errors.py`
- `src/adk_agent/sandbox/guard.py`
- `src/adk_agent/sandbox/worker.py`
- `src/adk_agent/sandbox/runner.py`
- `tests/sandbox/helpers.py`
- `tests/sandbox/test_sandbox_policy.py`
- `tests/sandbox/test_tool_sandbox.py`
- `tests/sandbox/test_wiring.py`
- `tests/tools/test_gateway_sandbox.py`
- `tests/test_egress_allowlist.py`
- `docs/evidence/SLICE-022-tool-sandbox.txt`

## 修改文件

- `src/adk_agent/config.py`：`AgentConfig.sandbox`
- `src/adk_agent/factory.py`：出口白名单检查
- `src/adk_agent/tools/gateway.py`：`sandbox` 参数和沙箱执行
- `src/adk_agent/console.py`：默认沙箱，包装 agent 工具
- `src/adk_agent/__init__.py`：导出沙箱类型
- `.importlinter`：`core` 禁止导入 `adk_agent.sandbox`
- `docs/contracts/framework_config.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：M2 完成

## 完成判据（可执行）

- [x] 策略校验超时、内存、主机名 -> `tests/sandbox/test_sandbox_policy.py`
- [x] 沙箱返回普通结果 -> `tests/sandbox/test_tool_sandbox.py::test_sandbox_returns_result`
- [x] 超时抛 `SandboxTimeout`，子进程被终止 -> `::test_sandbox_timeout`
- [x] 默认禁止网络 -> `::test_sandbox_denies_network`
- [x] 白名单主机可连接 -> `::test_sandbox_allows_listed_host`
- [x] 工具异常保留类名 -> `::test_sandbox_preserves_error_class`
- [x] 子进程环境变量被清空 -> `::test_sandbox_clears_environment`
- [x] 内存上限生效 -> `::test_sandbox_memory_limit`
- [x] 包装函数保留工具名 -> `tests/sandbox/test_wiring.py::test_sandboxed_callable_preserves_name`
- [x] `install_tool_sandbox` 覆盖子 agent，跳过工具集 -> `::test_install_tool_sandbox_wraps_callables_and_subagents`
- [x] ADK 工具循环经过沙箱 -> `::test_agent_tool_call_runs_in_sandbox`
- [x] 网关超时写 `error` 审计 -> `tests/tools/test_gateway_sandbox.py::test_gateway_timeout_is_audited`
- [x] 网关网络拒绝写 `error` 审计 -> `::test_gateway_network_denial_is_audited`
- [x] MCP URL 不在白名单时建 agent 失败 -> `tests/test_egress_allowlist.py::test_mcp_url_denied`
- [x] MCP URL 在白名单时通过 -> `::test_mcp_url_allowed`
- [x] OpenAPI server 不在白名单时失败 -> `::test_openapi_host_denied`
- [x] `allowed_hosts=None` 不限制已有配置 -> `::test_none_allowlist_allows`
- [x] `allowed_hosts=[]` 拒绝所有 HTTP 工具源 -> `::test_empty_allowlist_denies_all`
- [x] 配置契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.sandbox import ToolSandbox` -> 当前 `ModuleNotFoundError` -> 测试收集失败
- [x] 反例 2：工具睡过超时仍然返回 -> 期望 `SandboxTimeout`
- [x] 反例 3：工具联网成功 -> 期望 `SandboxViolation`
- [x] 反例 4：工具读到父进程的环境变量 -> 期望子进程环境为空
- [x] 反例 5：MCP URL 指向未授权主机仍然建 agent -> 期望失败
- [x] 反例 6：OpenAPI server 指向未授权主机仍然建 agent -> 期望失败

## 契约

### 策略

```python
class SandboxPolicy(BaseModel):
    timeout_seconds: float = 10.0
    max_cpu_seconds: int | None = None
    max_memory_mb: int | None = None
    allow_network: bool = False
    allowed_hosts: list[str] | None = None
    env_allowlist: list[str] = []
```

- `allowed_hosts=None` 表示 HTTP 工具源不加出口白名单。已有配置不受影响。
- `allowed_hosts=[]` 表示拒绝所有 HTTP 工具源。
- `allowed_hosts=["api.example.com"]` 表示只允许这些主机。
- 本地工具的出口规则：`allow_network=True` 放行全部；否则只放行 `allowed_hosts` 里的主机。
- `env_allowlist` 是子进程保留的环境变量名。默认空，工具读不到密钥。
- 主机名是小写字母、数字、点和连字符。不接受协议、端口或路径。

### 执行

```python
class ToolSandbox:
    def __init__(self, policy: SandboxPolicy | None = None) -> None: ...
    def invoke(self, handler: Callable, args: tuple, kwargs: dict) -> Any: ...

class SandboxError(Exception):
    error_code: str

class SandboxTimeout(SandboxError): ...
class SandboxViolation(SandboxError): ...

def sandboxed_callable(handler: Callable, sandbox: ToolSandbox) -> Callable: ...
def install_tool_sandbox(agent: Any, sandbox: ToolSandbox | None = None) -> None: ...
```

- POSIX：`fork` 子进程。子进程设置 `RLIMIT_CPU` 和 `RLIMIT_AS`，清空环境，安装 socket 守卫，调用 handler。
- 子进程默认拒绝 `getaddrinfo`、`connect`、`connect_ex`。AF_UNIX 不受限。
- 白名单主机先通过 `getaddrinfo` 解析，解析出的 IP 才允许 `connect`。
- Windows：模块能在子进程按名字导入时用 `spawn`。否则退化为守护线程超时。线程模式没有网络和资源隔离。
- 子进程结果是 pickle 的。不可序列化的结果返回 `SandboxSerializationError`。
- handler 异常返回原异常类名，调用方收到 `SandboxToolError`，`error_code` 是原类名。
- 超时后 `terminate`，再 `kill`。进程退出但没回结果时返回 `SandboxViolation`。
- `sandboxed_callable` 返回 async wrapper，保留 `__name__` 和签名。ADK 把它当 async 工具。
- `install_tool_sandbox` 只包装普通 callable。`BaseTool` 和 `BaseToolset` 跳过。
- 网关有 `sandbox` 参数。有沙箱时同步调用沙箱，没有沙箱时保持原行为。

### 出口白名单

```python
def check_url(url: str, policy: SandboxPolicy) -> None: ...
```

- MCP `transport="http"` 的 `url` 在建 agent 时检查。
- OpenAPI `servers[].url` 在建 agent 时检查。文档没有 `servers` 时不检查。
- 主机不在白名单时抛 `SandboxViolation`。
- ADK 自己的 OpenAPI 私网防护继续保留。两层都生效。

## 5 问威胁建模（10 分钟）

1. **数据**：工具参数、工具结果、环境变量、网络目标、进程资源。
2. **调用方**：工具网关、ADK 工具循环、控制台、工厂。
3. **信任边界**：工具代码、模型生成的参数、OpenAPI 文档、MCP URL。
4. **恶意输入最坏结果**：工具把数据发到外部网络；工具读走模型 API Key；工具耗尽 CPU 或内存；HTTP 工具源访问内网。分别用 socket 守卫、环境清空、rlimit、出口白名单处理。
5. **失败是否泄露信息**：超时和违规信息只写工具名和原因。审计只存参数和结果的 hash。子进程不继承环境变量。

### 已知边界

- `fork` 子进程共享父进程的内存映像。环境变量已清空，网络连接被守卫拦住，但继承的文件描述符还在。强隔离需要容器或独立解释器，排在 M5。
- Windows 的线程退化没有网络和资源隔离。从文件路径加载的 agent 模块（例如控制台）走这条路径。CI 在 Linux 上验证进程路径。
- 沙箱期间阻塞事件循环，最长 `timeout_seconds`。这是为了避开线程里 `fork` 的风险。
- MCP stdio 子进程的资源限制没有做。它由外部命令自己管理。
- `BaseTool` 实例和工具集不包装。OpenAPI/MCP 的隔离靠出口白名单和 ADK 私网防护。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.sandbox'`，5 个测试模块收集失败
- 实现后绿: 目标测试 35 passed, 1 skipped
- `check.py --fast` -> 183 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 183 passed, 1 skipped，9 步全 PASS
- Linux 容器: 沙箱测试 23 passed。全量 182 passed，1 个环境失败，容器没有 git
- 详见 `docs/evidence/SLICE-022-tool-sandbox.txt`
