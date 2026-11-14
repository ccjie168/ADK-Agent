# SLICE-086 连接器执行适配器

状态: merged
依据: ADR-0013 第 2、3、4 条。

## 意图（要什么，不写怎么写）

连接器注册好了，还没有执行路径。这一刀把连接器变成工具，并在发出请求前强制执行出站策略。

- `tools/connectors.py`：`ConnectorDenied`、`build_connector_tools`、默认 httpx 适配器（流式读取并截断）。
- 每个启用的连接器生成一个工具，`tool_id` 是 `connector_id`；参数是 `path`、`method`、`query`、`json_body`。
- 出站检查：方法在白名单、路径以 `/` 开头且命中前缀、无 `..`、host/scheme 与 `base_url` 一致、禁止重定向、超时与响应大小上限。
- 凭据经 `SecretProvider` 解析 `secret://` 引用，失败返回 `secret_unavailable`，不降级匿名。
- `ToolSpec` 增加 `egress`，连接器工具标为 `third_party`，工具网关审计按它写 `egress`。
- `serve-tool-gateway` 接受 `--connectors-dir DIR` 或 `CONNECTOR_URL`、`--connector-tenant TENANT`，把连接器工具与 `--tools` 合并。
- 新增 `PrefixedEnvSecretProvider`：`secret://crm/token` 映射到 `ADK_SECRET_CRM_TOKEN`。

## 新增文件

- `src/adk_agent/tools/connectors.py`
- `tests/tools/test_connector_tools.py`
- `docs/evidence/SLICE-086-connector-execution.txt`

## 修改文件

- `src/adk_agent/tools/registry.py`、`tools/gateway.py`、`tools/__init__.py`
- `src/adk_agent/secretstore/providers.py`、`secretstore/__init__.py`
- `src/adk_agent/cli.py`
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ToolSpec += egress: "none" | "third_party"

build_connector_tools(specs, *, secrets, adapter=None) -> [ToolSpec]
  handler(path, method="GET", query=None, json_body=None) -> dict

ConnectorDenied(error_code): method_denied | path_denied | egress_denied |
  response_too_large | secret_unavailable | connector_unavailable

PrefixedEnvSecretProvider("ADK_SECRET_"): secret://crm/token -> ADK_SECRET_CRM_TOKEN
```

## 完成判据（可执行）

- [x] 允许的请求发出并带 Bearer -> `tests/tools/test_connector_tools.py::test_allowed_request`
- [x] 方法不在白名单被拒 -> `::test_method_denied`
- [x] 路径前缀与穿越被拒 -> `::test_path_denied`
- [x] 重定向被拒 -> `::test_redirect_denied`
- [x] 响应超限被拒 -> `::test_response_too_large`
- [x] 凭据缺失被拒 -> `::test_secret_unavailable`
- [x] 工具标为 third_party 且审计体现 -> `::test_gateway_audits_third_party`
- [x] 前缀环境变量解析 -> `::test_prefixed_env_provider`
- [x] CLI 合并连接器工具 -> `::test_cli_merges_connectors`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools import ConnectorDenied` -> 当前 `ImportError`
- [x] 反例 2：出站方法越界仍执行 -> 当前无适配器
- [x] 反例 3：`ToolSpec(egress=...)` -> 当前 `TypeError`

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md` 的工具网关一节。

## 5 问威胁建模（10 分钟）

1. **数据**：端点、方法、路径、查询、凭据、响应。
2. **调用方**：工具网关、MCP、控制台。
3. **信任边界**：模型生成的参数到外部网络。
4. **恶意输入最坏结果**：SSRF 到任意 host（缓解：host 固定、路径相对、禁止重定向）；方法越权（缓解：白名单）；凭据泄露到日志（缓解：只放请求头、错误不回显）；超大响应耗尽内存（缓解：流式上限）。
5. **失败是否泄露信息**：错误码固定，不回显 URL 或令牌。

## 范围外

- OpenAPI 自动生成多个工具。
- MCP 连接器的执行（v1 只做 HTTP）。
- 响应转换 DSL 与 OAuth。

## 证据

- 反例红: `docs/evidence/SLICE-086-connector-execution.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，本地回环 HTTP 服务
