# SLICE-021 密钥与外部工具源（M2-3）

状态: gated
依据: ADR-0002 第 5、6 条

## 意图（要什么，不写怎么写）

让 agent 安全地接入外部工具源。

- `SecretProvider` 有可用的适配器。默认从环境变量取值。
- 配置里只写密钥引用，不写密钥值。
- MCP HTTP 和 OpenAPI 工具的认证头在请求时解析，不落配置、不落审计。
- OpenAPI JSON 文档可以变成 ADK 工具集。
- 控制台给 OpenAPI 工具和 MCP `tool_filter` 里的工具发 grant。未知工具继续拒绝。
- 这一刀不做工具沙箱。沙箱是 SLICE-022。

## 新增文件

- `src/adk_agent/secretstore/__init__.py`
- `src/adk_agent/secretstore/providers.py`
- `src/adk_agent/tools/sources.py`
- `tests/secretstore/test_secret_providers.py`
- `tests/tools/test_sources.py`
- `tests/mcp/test_client.py`
- `docs/evidence/SLICE-021-secrets-and-tool-sources.txt`

包名用 `secretstore`，不用 `secrets`。仓库的 `.claude/settings.json` 拒绝读取 `secrets/`，代码目录会误触。

## 修改文件

- `src/adk_agent/config.py`：`OpenApiConfig`、`McpServerConfig.header_secrets`、`AgentConfig.openapi`
- `src/adk_agent/factory.py`：默认 `EnvSecretProvider`，构建 OpenAPI 工具集
- `src/adk_agent/mcp/client.py`：`secrets` 参数和 `header_provider`
- `src/adk_agent/tools/__init__.py`：导出工具源函数
- `src/adk_agent/console.py`：按工具集发 grant
- `src/adk_agent/__init__.py`：导出新类型
- `.importlinter`：`core` 禁止导入 `adk_agent.secretstore`
- `docs/contracts/framework_config.schema.json`：重新生成
- `docs/specs/ROADMAP.md`：标出 SLICE-021 完成

## 完成判据（可执行）

- [x] 环境变量密钥可解析 -> `tests/secretstore/test_secret_providers.py::test_env_provider_resolves`
- [x] 缺失或非法引用抛 `SecretNotFound`，错误不含密钥值 -> `::test_env_provider_missing`、`::test_env_provider_rejects_invalid_reference`
- [x] 密钥值含 CR/LF 被拒绝，防头部注入 -> `::test_env_provider_rejects_newline`
- [x] 映射提供者用于测试和注入 -> `::test_mapping_provider`
- [x] 认证头在请求时解析 -> `::test_secret_header_provider`
- [x] 非法头名在构建时拒绝 -> `::test_secret_header_provider_rejects_bad_name`
- [x] MCP HTTP 工具集从 `header_secrets` 解析认证头 -> `tests/mcp/test_client.py::test_http_toolset_resolves_header_secrets`
- [x] MCP 配置了 `header_secrets` 但没提供者时构建失败 -> `::test_header_secrets_require_provider`
- [x] stdio MCP 不允许 `header_secrets` -> `::test_stdio_header_secrets_rejected`
- [x] `headers` 和 `header_secrets` 同名时配置拒绝 -> `::test_overlapping_headers_rejected`
- [x] MCP `tool_filter` 成为声明的工具名 -> `::test_tool_filter_is_declared`
- [x] OpenAPI JSON 生成工具集 -> `tests/tools/test_sources.py::test_openapi_toolset_from_json`
- [x] OpenAPI 工具名和前缀进入声明 -> `::test_openapi_tool_ids_apply_prefix`
- [x] OpenAPI 认证头在请求时解析 -> `::test_openapi_header_secrets`
- [x] 非对象 OpenAPI 文档被拒绝 -> `::test_openapi_rejects_non_object`
- [x] `build_agent` 默认用环境变量提供者并构建 OpenAPI 工具 -> `::test_build_agent_includes_openapi_toolset`
- [x] 控制台给 OpenAPI 工具发 grant -> `tests/test_console_tools.py::test_console_grants_openapi_toolset_tools`
- [x] 控制台给 MCP `tool_filter` 发 grant，其他工具拒绝 -> `tests/test_console_tools.py::test_console_grants_mcp_filter_tools`
- [x] 配置契约 schema 与模型同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.secretstore import EnvSecretProvider` -> 当前 `ModuleNotFoundError` -> 测试收集失败
- [x] 反例 2：配置写 `openapi` -> 当前 `ValidationError`，未知字段
- [x] 反例 3：配置写 `header_secrets` -> 当前 `ValidationError`，未知字段
- [x] 反例 4：MCP 工具集的 `read_file` 被守卫拒绝 -> 当前控制台跳过工具集，期望放行
- [x] 反例 5：OpenAPI 工具没有 builder -> 当前无法从 JSON 生成工具集
- [x] 反例 6：密钥值含换行仍然进入请求头 -> 期望构建或解析时拒绝

## 契约

### 配置

```python
class OpenApiConfig(BaseModel):
    spec_path: str
    tool_filter: list[str] | None = None
    tool_name_prefix: str | None = None
    header_secrets: dict[str, str] = {}   # header name -> secret reference

class McpServerConfig(BaseModel):
    ...
    header_secrets: dict[str, str] = {}   # http only

class AgentConfig(BaseModel):
    ...
    openapi: list[OpenApiConfig] = []
```

- 密钥引用格式是环境变量名，`^[A-Za-z_][A-Za-z0-9_]*$`。配置里禁止写密钥值。
- `header_secrets` 的键是 HTTP 头名，`^[A-Za-z0-9-]+$`。
- `headers` 和 `header_secrets` 不能有同名键。
- 只有 `http` MCP 支持 `header_secrets`。

### 密钥提供者

```python
class SecretProvider(Protocol):
    async def resolve(self, reference: str) -> str: ...

class SecretNotFound(Exception): ...

class EnvSecretProvider:
    async def resolve(self, reference: str) -> str: ...

class MappingSecretProvider:
    def __init__(self, values: Mapping[str, str]) -> None: ...
    async def resolve(self, reference: str) -> str: ...

def secret_header_provider(
    secrets: SecretProvider, header_refs: Mapping[str, str]
) -> Callable[[Any], Awaitable[dict[str, str]]]: ...
```

- `EnvSecretProvider` 只读环境变量。非法引用、未设置、空值都抛 `SecretNotFound`。
- 密钥值含 `\r` 或 `\n` 时抛 `SecretNotFound`。错误只写引用名，不写值。
- `secret_header_provider` 每次请求调用 `resolve`。返回值直接进入请求头。
- 默认提供者是 `EnvSecretProvider`。`build_agent` 在没传提供者时使用它，并传给子 agent。

### 工具源

```python
def load_openapi_spec(path: str) -> dict[str, Any]: ...
def openapi_toolset_from_config(
    cfg: OpenApiConfig, secrets: SecretProvider
) -> Any: ...
def toolset_tool_ids(toolset: Any) -> set[str]: ...
```

- 只接受 JSON 对象。非 JSON 或非对象抛 `ValueError`。
- `OpenAPIToolset` 保持 `allow_private_network_access=False`，拒绝回环、私网、链路本地和云元数据地址。
- `toolset_tool_ids` 取 `declared_tool_ids`、`_tools` 或 `tool_filter`，应用 `tool_filter` 交集和 `tool_name_prefix`。
- MCP 工具集没有列表 `tool_filter` 时，控制台拿不到工具名。所有工具拒绝。这是 fail closed。
- `McpToolset.tool_filter` 是工具名列表时，控制台放行这些工具，其他拒绝。

## 5 问威胁建模（10 分钟）

1. **数据**：密钥引用、密钥值、认证头、OpenAPI 文档、工具名、工具参数。
2. **调用方**：工厂、CLI、控制台、外部 MCP 服务器、外部 HTTP API。
3. **信任边界**：环境变量、配置文件、OpenAPI 文档、MCP 服务器返回的工具列表。
4. **恶意输入最坏结果**：密钥值带换行导致头部注入；配置里写了密钥值被提交；OpenAPI 文档指向内网或云元数据；工具集绕过 grant。分别用值校验、引用格式校验、ADK 私网默认拒绝、控制台工具集 grant 处理。
5. **失败是否泄露信息**：`SecretNotFound` 只写引用名。审计只存参数 hash。模型调用和工具调用不会收到密钥值。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.secretstore'`，4 个测试模块收集失败
- 实现后绿: 目标测试 25 passed
- `check.py --fast` -> 152 tests，7 步全 PASS
- `check.py --full` -> 152 tests，9 步全 PASS
- 详见 `docs/evidence/SLICE-021-secrets-and-tool-sources.txt`
