# SLICE-089 连接器健康检查

状态: merged
依据: ADR-0013 后果段（“注册错误的连接器会在首次调用时暴露，而不是启动时（可选加健康检查）”）。

## 意图（要什么，不写怎么写）

连接器注册后，配置错误要到第一次工具调用才暴露。这一刀给运营一个主动检查入口：对连接器发一个受约束的探测请求，回一个结构化结论。

- 新增纯异步函数，把 `ConnectorSpec` 探测成 `ConnectorHealth`。
- 控制台新增 `POST /api/connectors/{id}/check` 与 Check 按钮，只有 admin 能触发。
- CLI `adk-agent connectors check --id ID`，支持文件存储与控制面。
- 探测沿用连接器自身的出站约束，不发凭据、不跟随重定向、不读响应体、超时封顶。
- 不落库、不定时调度、不改工具执行路径。

## 新增文件

- `src/adk_agent/registry/connector_health.py`
- `tests/registry/test_connector_health.py`
- `docs/evidence/SLICE-089-connector-health.txt`
- `docs/specs/SLICE-089-connector-health.md`

## 修改文件

- `src/adk_agent/registry/__init__.py`（导出）
- `src/adk_agent/console.py`（检查接口与按钮）
- `src/adk_agent/cli.py`（`connectors check`）
- `tests/test_console_connectors.py`、`tests/test_cli_connectors.py`
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ConnectorHealth {
  connector_id: str,
  status: "healthy" | "unauthorized" | "not_found" | "redirect"
        | "server_error" | "unexpected_status" | "unreachable",
  status_code: int | null,
  latency_ms: int,
  checked_at: datetime (UTC),
  reason: "timeout" | "connect_error" | null
}

check_connector(spec, *, client=None, max_timeout=5.0) -> ConnectorHealth

探测请求：
  GET {base_url.rstrip("/") + path_prefixes[0]}
  无 Authorization 头，不解析 auth_ref
  follow_redirects=False
  超时 = min(spec.timeout_seconds, max_timeout)
  响应体不读取（流式打开后立即关闭）

分类：
  2xx -> healthy
  3xx -> redirect
  401/403 -> unauthorized
  404 -> not_found
  5xx -> server_error
  其他 -> unexpected_status
  传输超时 -> unreachable, reason="timeout"
  其他传输错误 -> unreachable, reason="connect_error"

console:
  POST /api/connectors/{id}/check -> ConnectorHealth
CLI:
  connectors check --id ID [--connectors-dir DIR | --registry-url URL]
```

## 完成判据（可执行）

- [x] 2xx 判健康 -> `tests/registry/test_connector_health.py::test_healthy`
- [x] 401/403 判未授权 -> `::test_unauthorized`
- [x] 404 判不存在 -> `::test_not_found`
- [x] 3xx 判重定向且不跟随 -> `::test_redirect_not_followed`
- [x] 5xx 判服务端错误 -> `::test_server_error`
- [x] 其他状态判意外 -> `::test_unexpected_status`
- [x] 连接错误判不可达 -> `::test_connect_error`
- [x] 超时判不可达且带 reason -> `::test_timeout`
- [x] 请求不带凭据、只打第一个路径前缀 -> `::test_request_shape`
- [x] 控制台检查只有 admin 能触发 -> `tests/test_console_connectors.py::test_check_admin_only`
- [x] 控制台未知 id 与跨租户 -> `::test_check_missing_and_tenant`
- [x] CLI 文件存储检查 -> `tests/test_cli_connectors.py::test_cli_check_file`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import check_connector` -> 当前 `ImportError`
- [x] 反例 2：`POST /api/connectors/{id}/check` -> 当前 404
- [x] 反例 3：`adk-agent connectors check --id X` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：连接器基础 URL、路径前缀、超时、状态码、延迟。
2. **调用方**：控制台 admin、CLI 操作者。
3. **信任边界**：探测请求从控制台或 CLI 主机发出，目标是第三方端点。
4. **恶意输入最坏结果**：借检查打内网地址（缓解：只允许 admin 触发，URL 仍受连接器校验约束，只打已注册且可见的连接器）；凭据外泄（缓解：不解析 `auth_ref`、不发 Authorization 头）；响应体被读入内存或落盘（缓解：流式打开后不读，解析结果只含状态码）；无限等待（缓解：超时取连接器配置与 5 秒的较小值）；跨租户探测别家连接器（缓解：复用可见性检查）。
5. **失败是否泄露信息**：只回固定状态枚举与状态码，不回显响应体、URL 细节或 DSN。

## 范围外

- 定时健康检查与结果持久化。
- 控制面侧的检查端点。
- 带凭据的探测。
- 对 `kind="openapi"` 与 `kind="mcp"` 的专门探测协议。

## 证据

- 反例红：`docs/evidence/SLICE-089-connector-health.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，回环服务器与真实 httpx
