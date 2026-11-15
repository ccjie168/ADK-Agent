# SLICE-001 MCP streamable-http + 强制鉴权

状态: merged

## 意图（要什么，不写怎么写）

把 ADK agent 通过 MCP 的 `streamable-http` 传输暴露出来，使 Claude Code 或远端
客户端能通过 HTTP 调用；**默认拒绝未鉴权端点**，每个 HTTP 端点都有 Bearer
鉴权声明（CP-S6）。本切片不含 Cloud Run 部署（另开切片），但为其预留
`host` / `port` / token 注入。

## 完成判据（可执行）

- [x] 判据 1：`serve_agent(..., transport="streamable-http", auth_token=...)` 能启动；
      客户端带 `Authorization: Bearer <token>` 可 `initialize` 并 `list_tools`
      -> `tests/test_http_auth.py::test_http_mcp_client_roundtrip`
- [x] 判据 2：无 `Authorization` 头的请求返回 401
      -> `tests/test_http_auth.py::test_http_requires_bearer`
- [x] 判据 3：错误 token 返回 401
      -> `tests/test_http_auth.py::test_http_rejects_wrong_token`
- [x] 判据 4：非 loopback host 且未提供 token 时，启动前抛 `ValueError`
      -> `tests/test_http_auth.py::test_http_rejects_unauthenticated_public_bind`
- [x] 判据 5：`check.py --fast` 与 `--full` 全绿

## 反例（必须在实现前跑红）

- [x] 反例 1：无鉴权请求 -> 期望 401（当前实现：HTTP 端点无鉴权，返回非 401）
- [x] 反例 2：错误 token -> 期望 401
- [x] 反例 3：`host=0.0.0.0` 且无 token -> 期望启动前报错（当前：会直接启动）
- [x] 反例 4：`allow_unauthenticated=True` 但 `host=0.0.0.0` -> 期望报错
      （免鉴权只能用于 loopback）

## 契约（如涉及对外接口）

- Endpoint: `POST /mcp`（MCP streamable-http）
- Auth: `Authorization: Bearer <token>`；缺失或错误 -> `401` + `WWW-Authenticate: Bearer`
- 配置：`host`（默认 `127.0.0.1`）、`port`（默认 `8000`）、`auth_token`、
  `allow_unauthenticated`（仅限 loopback）

## 5 问威胁建模（10 分钟）

1. **数据**：agent 的输入/输出可能含内部代码与配置；不含生产 PII（见 ADR-0001）。
2. **调用方**：Claude Code（本地或远端）、未来的远端 MCP 客户端。
3. **信任边界**：HTTP 端点跨机器/网络边界，必须鉴权。
4. **恶意输入最坏结果**：未鉴权调用可驱动 agent 调用其工具（读文件/执行命令）
   -> 写成反例（401）。
5. **失败是否泄露信息**：401 只返回 `{"error":"unauthorized"}`，不泄露 token 或内部细节。

## 证据

- **反例红（实现前）**：`pytest tests/test_http_auth.py` ->
  `ModuleNotFoundError: No module named 'adk_agent.mcp.http'`（反例无法通过）。
- **实现后绿**：
  - `pytest tests/test_http_auth.py` -> 5 passed
  - 全量 `pytest` -> 11 passed
  - `check.py --fast` / `--full` -> ALL PASS
  - 真实 HTTP 端到端（CLI 启动 minimal agent）：
    - 无 token -> `401`
    - 带 `Authorization: Bearer secret` -> `list_tools` 返回 `['minimal_agent']`
    - `call_tool` -> `get_time` 返回 `2026-11-10 23:11:01`，`isError: False`

## 备注

- 本机存在系统 HTTP 代理（Privoxy），测试客户端必须 `trust_env=False`，
  否则 loopback 请求会被代理拦截并返回 500。生产服务端不受影响。
- `allow_unauthenticated=True` 仅允许 loopback；非 loopback 一律拒绝启动。
