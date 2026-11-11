# SLICE-011 模型与配置契约收敛（M0-4）

状态: gated
依据: ADR-0002 第 2、3、8 条，评审发现 1、2、3

## 意图（要什么，不写怎么写）

收敛配置和模型通道的三个分歧。

- `thinking_budget` 是生成配置，不是模型属性。它从 `ModelConfig` 移到 `AgentConfig`，只有 `build_agent` 读取。`ModelConfig` 拒绝该字段，避免 `build_model` 静默忽略。
- `build_model` 不再写 `os.environ`。Gemini 用 `client_kwargs` 传 key，进程环境只读。
- 入向 MCP 传输和出向暴露传输是两个不同概念。用 `IncomingTransport` 与 `ExposureTransport` 命名区分，不强行合并成一个 literal。
- 鉴权从 `mcp.http` 抽到 `adk_agent.auth`，MCP HTTP 和控制台共用。`core` 通过 import-linter 禁止导入它。
- `FrameworkConfig` 纳入契约导出，改配置接口前先改契约。

## 新增文件

- `src/adk_agent/auth.py`
- `tests/test_model_env.py`
- `docs/contracts/framework_config.schema.json`（生成）

## 修改文件

- `src/adk_agent/config.py`
- `src/adk_agent/factory.py`
- `src/adk_agent/models.py`
- `src/adk_agent/mcp/http.py`
- `src/adk_agent/console.py`
- `scripts/export_contracts.py`
- `docs/contracts/README.md`
- `.importlinter`
- `examples/minimal/framework.json`
- `tests/test_config_thinking.py`
- `tests/test_http_auth.py`

## 完成判据（可执行）

- [x] `AgentConfig.thinking_budget: int | None` 生效 -> `tests/test_config_thinking.py::test_thinking_budget_is_applied`
- [x] `ModelConfig` 拒绝 `thinking_budget` -> `::test_model_config_rejects_thinking_budget`
- [x] `build_model` 不写 `GOOGLE_API_KEY` -> `tests/test_model_env.py::test_gemini_key_does_not_mutate_env`
- [x] 已存在的 `GOOGLE_API_KEY` 不被覆盖 -> `::test_gemini_key_does_not_override_env`
- [x] `adk_agent.auth` 提供中间件和解析函数 -> `tests/test_http_auth.py` 从新路径导入并通过
- [x] `core` 不得导入 `adk_agent.auth` -> `tests/test_layering.py::test_core_isolation`
- [x] `docs/contracts/framework_config.schema.json` 与模型一致 -> `tests/core/test_contracts.py::test_contracts_in_sync`
- [x] `examples/minimal/framework.json` 的 `thinking_budget` 在 agent 层

## 反例（必须在实现前跑红）

- [x] 反例 1：`ModelConfig(..., thinking_budget=0)` -> 当前接受，期望 `ValidationError` -> `test_model_config_rejects_thinking_budget`
- [x] 反例 2：`AgentConfig(..., thinking_budget=0)` -> 当前被 `extra="forbid"` 拒绝，期望接受并生效 -> `test_thinking_budget_is_applied`
- [x] 反例 3：`build_model(ModelConfig(api_key="secret"))` -> 当前写入 `GOOGLE_API_KEY`，期望不写 -> `test_gemini_key_does_not_mutate_env`
- [x] 反例 4：`from adk_agent.auth import resolve_http_auth` -> 当前 `ModuleNotFoundError` -> `tests/test_http_auth.py` 收集失败
- [x] 反例 5：`framework_config.schema.json` 缺失 -> `test_contracts_in_sync` 失败

## 契约

### 配置字段迁移

```python
class ModelConfig(BaseModel):
    provider: Literal["gemini", "litellm", "claude", "vertex"] = "litellm"
    name: str = "deepseek/deepseek-v4-pro"
    api_key: str | None = None
    api_base: str | None = None
    kwargs: dict[str, Any] = {}

class AgentConfig(BaseModel):
    name: str
    description: str = ""
    instruction: str = ""
    thinking_budget: int | None = None
    model: ModelConfig = ModelConfig()
    mcp_servers: list[McpServerConfig] = []
    sub_agents: list[AgentConfig] = []
```

`thinking_budget` 非 None 时 `build_agent` 传入 `GenerateContentConfig(thinking_config=ThinkingConfig(thinking_budget=...))`。

### 传输类型

```python
IncomingTransport = Literal["stdio", "http"]
ExposureTransport = Literal["stdio", "streamable-http"]
```

`McpServerConfig.transport: IncomingTransport`。`FrameworkConfig.transport: ExposureTransport`。两者是不同方向，值不同是有意的。

### 鉴权

`adk_agent.auth` 提供 `LOOPBACK_HOSTS`、`OPEN_PATHS`、`BearerAuthMiddleware`、`resolve_http_auth`。`mcp.http` 和 `console` 从它导入。`resolve_port` 留在 `mcp.http`。

### 契约导出

`scripts/export_contracts.py` 增加 `framework_config.schema.json`，由 `FrameworkConfig` 生成。该 schema 在 M1 由 `AgentManifest` 取代，过渡期保留。

## 5 问威胁建模（10 分钟）

1. **数据**：模型 API key、配置 JSON、bearer token。
2. **调用方**：CLI、配置驱动的工厂、MCP HTTP、控制台。
3. **信任边界**：配置文件、环境变量、HTTP 请求。
4. **恶意输入最坏结果**：配置文件把 key 写进错误字段导致泄漏或静默失效；环境写入让同进程其他 agent 复用同一 key。字段迁移、`extra="forbid"` 和 `client_kwargs` 分别处理。
5. **失败是否泄露信息**：配置错误只回显字段名和规则；key 不出现在日志或异常文本。

## 证据

- 反例红: `pytest tests/test_config_thinking.py tests/test_model_env.py tests/core/test_contracts.py::test_contracts_in_sync -q` -> `5 failed, 1 passed`；`tests/test_http_auth.py` 收集失败 `ModuleNotFoundError: No module named 'adk_agent.auth'`
- 实现后绿: 目标测试 28 passed，契约测试 12 passed
- `check.py --fast` -> 57 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-011-contract-convergence.txt`
