# Trace 传播契约

## 入站

控制台聊天和 MCP HTTP 接受两种 trace 头。

- `X-Trace-Id` 优先。值必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则忽略。
- 没有合法的 `X-Trace-Id` 时读 W3C `traceparent`，格式是 `<version>-<trace-id>-<parent-id>-<flags>`。版本和 trace-id 不能全零，版本不能是 `ff`，各段用小写十六进制。取其中的 32 位 trace-id。
- 两者都没有时生成 32 位小写十六进制。

控制台用它作为本次 run 的 `trace_id`，MCP 审计也用它。

## 出站

`HttpModelGateway` 和 `HttpToolGateway` 的请求带 `X-Trace-Id`，值是 `Invocation.trace_id`。服务端审计继续使用请求体 `invocation.trace_id`，所以两侧的 trace 一致。

MCP 客户端到 MCP 服务的 `traceparent` 由调用方决定，服务端只负责读取和记录。
