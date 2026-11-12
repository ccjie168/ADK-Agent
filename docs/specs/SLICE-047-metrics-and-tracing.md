# SLICE-047 指标与 trace 传播

状态: gated
依据: SLICE-028，SLICE-036，SLICE-041，SLICE-046，`docs/contracts/console.md`，`docs/contracts/tracing.md`

## 意图（要什么，不写怎么写）

给平台补上进程内指标和跨边界的 trace 传播。不新增依赖。

- 新增 `MetricsRegistry`，计数器、summary 和 Prometheus 文本渲染都在标准库里做。
- `AgentRuntime` 和 `PlanExecutor` 接受可选的注册表。没传就什么都不记。
- 控制台 `/metrics` 暴露本进程注册表，和其他 `/api/*` 一样要 bearer token。
- 控制台聊天接受 W3C `traceparent`，`X-Trace-Id` 仍然优先。
- MCP 审计的 `trace_id` 取调用方 `traceparent` 的 trace-id，没有时新生成。
- `HttpModelGateway` 和 `HttpToolGateway` 出站请求带 `X-Trace-Id`，值等于 `Invocation.trace_id`。

这一刀不做 MCP 和网关的 `/metrics` 端点，不接 OpenTelemetry，也不做跨副本指标聚合。

## 新增文件

- `src/adk_agent/metrics.py`：`MetricsRegistry`
- `src/adk_agent/tracing.py`：`trace_id_from_traceparent`、`resolve_trace_id`
- `tests/test_metrics.py`
- `tests/test_tracing.py`
- `tests/test_console_metrics.py`
- `tests/test_runtime_metrics.py`
- `tests/test_console_traceparent.py`
- `tests/test_mcp_trace.py`
- `tests/test_gateway_trace_headers.py`
- `docs/contracts/tracing.md`
- `docs/evidence/SLICE-047-metrics-and-tracing.txt`

## 修改文件

- `src/adk_agent/runtime/execution.py`：可选 `metrics` 和 `source`
- `src/adk_agent/orchestration/executor.py`：可选 `metrics`
- `src/adk_agent/mcp/runtime.py`：可选 `trace_id`
- `src/adk_agent/mcp/server.py`：从 ctx 读 `traceparent` 并传给包装
- `src/adk_agent/console.py`：`build_console_app(metrics=)`、`/metrics`、`_trace_id` 读 traceparent
- `src/adk_agent/models/http_gateway.py`、`src/adk_agent/tools/http_gateway.py`：出站 `X-Trace-Id`
- `docs/contracts/README.md`、`docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
MetricsRegistry:
  inc(name, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None
  observe(name, value: float, labels=None) -> None      # 写 <name>_sum 和 <name>_count
  render() -> str                                        # Prometheus 0.0.4 文本

AgentRuntime(runner, audit=None, metrics=None, source="agent")
PlanExecutor(agents, ..., metrics=None)
AuditedMcpRunner(..., trace_id=None)
```

指标：

```text
adk_agent_runs_total{source,tenant,agent,status}
adk_agent_run_duration_seconds        # summary: _sum/_count
adk_agent_quota_denials_total{tenant,limit}
adk_agent_plan_runs_total{tenant,plan,status}
adk_plan_duration_seconds             # summary: _sum/_count
```

- `source` 是 `console`（控制台注入的运行时）或 `agent`（库默认）。
- 配额拒绝同时加 `runs_total` 的 `denied` 和 `quota_denials_total`。
- 计划异常记 `status="error"`；`QuotaExceeded` 记 `denied` 并加配额拒绝计数。

trace 规则见 `docs/contracts/tracing.md`。`resolve_trace_id(x_trace_id, traceparent)` 先看合法的 `X-Trace-Id`，再看 `traceparent`，最后 `uuid4().hex`。

## 完成判据（可执行）

- [x] 计数器渲染 -> `tests/test_metrics.py::test_counter_render`
- [x] summary 渲染成 `_sum` 和 `_count` -> `tests/test_metrics.py::test_summary_render`
- [x] 标签排序和转义 -> `tests/test_metrics.py::test_labels_are_sorted_and_escaped`
- [x] 非法指标名被拒 -> `tests/test_metrics.py::test_invalid_metric_name_rejected`
- [x] 非法标签名被拒 -> `tests/test_metrics.py::test_invalid_label_name_rejected`
- [x] 空注册表渲染空串 -> `tests/test_metrics.py::test_empty_registry_renders_nothing`
- [x] 合法 traceparent 取 trace-id -> `tests/test_tracing.py::test_valid_traceparent`
- [x] 拒绝版本 ff -> `tests/test_tracing.py::test_rejects_version_ff`
- [x] 拒绝全零 trace-id -> `tests/test_tracing.py::test_rejects_zero_trace_id`
- [x] 拒绝畸形输入 -> `tests/test_tracing.py::test_rejects_malformed`
- [x] X-Trace-Id 优先 -> `tests/test_tracing.py::test_x_trace_id_wins`
- [x] 缺省时生成 32 位十六进制 -> `tests/test_tracing.py::test_generates_when_missing`
- [x] `/metrics` 需要 token -> `tests/test_console_metrics.py::test_metrics_require_token`
- [x] 聊天后出现运行计数和耗时 -> `tests/test_console_metrics.py::test_metrics_count_runs`
- [x] 配额拒绝计数 -> `tests/test_console_metrics.py::test_metrics_count_quota_denials`
- [x] 运行时记 ok 和 error -> `tests/test_runtime_metrics.py::test_runtime_counts_ok_and_error`
- [x] 计划执行记运行次数 -> `tests/test_runtime_metrics.py::test_plan_executor_counts_runs`
- [x] 计划配额拒绝计数 -> `tests/test_runtime_metrics.py::test_plan_quota_denial_counts`
- [x] 聊天使用 traceparent -> `tests/test_console_traceparent.py::test_traceparent_used`
- [x] X-Trace-Id 优先于 traceparent -> `tests/test_console_traceparent.py::test_x_trace_id_wins`
- [x] 畸形 traceparent 自动生成 -> `tests/test_console_traceparent.py::test_malformed_traceparent_generates`
- [x] MCP 审计用 traceparent -> `tests/test_mcp_trace.py::test_audit_uses_traceparent`
- [x] MCP 畸形 traceparent 自动生成 -> `tests/test_mcp_trace.py::test_malformed_traceparent_generates`
- [x] 模型网关客户端带 trace 头 -> `tests/test_gateway_trace_headers.py::test_model_gateway_sends_trace_header`
- [x] 工具网关客户端带 trace 头 -> `tests/test_gateway_trace_headers.py::test_tool_gateway_sends_trace_header`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.metrics import MetricsRegistry` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.tracing import trace_id_from_traceparent` -> 当前 `ImportError`
- [x] 反例 3：`GET /metrics` -> 当前路由不存在，返回 404
- [x] 反例 4：聊天带合法 `traceparent` -> 当前不使用，返回随机 trace_id
- [x] 反例 5：MCP 审计带 `traceparent` -> 当前每次随机，不读请求头
- [x] 反例 6：网关客户端出站请求 -> 当前只有 Authorization，没有 `X-Trace-Id`

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。已改：

- `tracing.md` 新增入站和出站规则。
- `console.md` 新增 `/metrics`，聊天 trace 头补 `traceparent`。
- `cli.md` 的 MCP 审计一节补 trace_id 来源。

## 5 问威胁建模（10 分钟）

1. **数据**：运行计数、耗时、租户和 agent 标签、trace id、请求头。
2. **调用方**：运维的 Prometheus、控制台用户、MCP host、网关客户端。
3. **信任边界**：抓取端到控制台，请求头到服务，服务到审计。
4. **恶意输入最坏结果**：伪造 `X-Trace-Id` 或 `traceparent` 把别人的 trace 串起来；指标标签基数爆炸拖垮内存；`/metrics` 泄露租户和 agent 名。缓解是标签只来自服务端对象（tenant/agent/status），不来自用户文本；trace 头只做格式校验和长度限制；`/metrics` 要 token；注册表只保存固定标签组合，单进程有界。指标不记请求内容。
5. **失败是否泄露信息**：`/metrics` 未鉴权返回 401，不带指标。非法 trace 头静默忽略，不报错。指标渲染不包含异常文本。

## 范围外

- MCP 和网关的 `/metrics` 端点。
- OpenTelemetry、span 和 trace 导出。
- 跨副本指标聚合和历史。
- 指标标签的租户白名单或按角色过滤。`/metrics` 是运维接口。
- 直方图分位数。只有 `_sum` 和 `_count`。

## 证据

- 反例红: `docs/evidence/SLICE-047-metrics-and-tracing.txt`，两个新模块 ImportError，`/metrics` 404，三个 trace 用例失败
- 实现后绿: 同文件，48 passed；`check.py --fast` ALL PASS（547 passed, 9 skipped），`--full` ALL PASS
- 真实控制台: 同文件，带 traceparent 的聊天返回同一个 trace_id，第二次聊天 429，`/metrics` 未鉴权 401，鉴权后出现 ok/denied 运行计数、耗时和配额拒绝
- 真实 MCP: 同文件，客户端带 traceparent 调用，审计事件的 trace_id 与之一致
