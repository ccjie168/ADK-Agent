# 工具网关客户端

`tools/client.py` 的 `ToolGatewayClient` 是父进程调用工具网关的唯一入口，用于沙箱工具中介。

## `POST /v1/invoke`

请求体是 `ToolGatewayRequest`（`invocation`、`request.tool_id`、`request.args`、`grants`），结构见
`tool_gateway_request.schema.json`。客户端带 `Authorization: Bearer <token>`，token 由调用方从环境变量读取。

- 200：响应是 `ToolResponse`，客户端返回 `output`。
- 403：抛 `ToolDenied`，执行器映射为 `tool_denied`。
- 5xx 或非 200：抛 `ToolGatewayError`，执行器映射为 `tool_gateway_unavailable`。
- 连接失败或超时：抛 `ToolGatewayError`，消息不包含地址以外的内部细节。
- 响应不是合法 `ToolResponse`：抛 `ToolGatewayError`。

执行器 `tools/executor.py` 的 `gateway_executor(client)` 返回
`async (manifest, tool_id, args, invocation) -> Mapping`：没有 `invocation` 时抛
`SandboxToolError("tool_principal_unavailable")`；非映射输出包装成 `{"output": ...}`。
