# Metrics 契约

所有端点输出 Prometheus 文本格式 0.0.4，`Content-Type` 是 `text/plain; version=0.0.4; charset=utf-8`。除 `/healthz` 外，端点和各服务一样需要 bearer token。

## 端点

- `GET /metrics`：控制台。
- `GET /metrics`：模型网关。
- `GET /metrics`：工具网关。
- `GET /metrics`：MCP 的 streamable-http 服务。只有带 `--metrics` 启动时存在。

A2A 目前没有 metrics 端点。

## 指标

- `adk_agent_runs_total{source,tenant,agent,status}`：agent 运行计数。`source` 是 `console`、`mcp` 或库默认的 `agent`。`status` 是 `ok`、`error` 或 `denied`。
- `adk_agent_run_duration_seconds{agent,tenant}`：summary，只有 `_sum` 和 `_count`。
- `adk_agent_quota_denials_total{tenant,limit}`：配额拒绝计数，`limit` 是 `max_runs` 或 `max_concurrent`。
- `adk_agent_plan_runs_total{plan,tenant,status}` 和 `adk_plan_duration_seconds{plan,tenant}`：只在注入同一个注册表时出现。
- `adk_model_calls_total{provider,status}` 和 `adk_model_call_duration_seconds{provider}`：模型网关。
- `adk_model_breaker_short_circuits_total{provider}`：熔断器打开期间被直接拒绝的调用数。
- `adk_tool_calls_total{tool,status}` 和 `adk_tool_call_duration_seconds{tool}`：工具网关。

## 聚合

每个进程只看自己的计数。跨副本聚合由抓取端负责，例如 Prometheus 对每个副本的 `/metrics` 做 `sum by (...)`。应用不把指标写进共享存储。
