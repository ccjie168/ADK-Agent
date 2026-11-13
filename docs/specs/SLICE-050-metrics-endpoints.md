# SLICE-050 服务指标端点

状态: gated
依据: SLICE-037，SLICE-038，SLICE-046，SLICE-047，`docs/contracts/metrics.md`

## 意图（要什么，不写怎么写）

SLICE-047 只给控制台开了 `/metrics`。模型网关、工具网关和 MCP 服务还没有可抓取的端点，MCP 运行计数也没有接上。这一刀补齐。

- 模型网关和工具网关默认暴露 `/metrics`，受现有 bearer 或 OIDC 中间件保护。
- 模型网关记 `adk_model_calls_total{provider,status}` 和耗时 summary。工具网关记 `adk_tool_calls_total{tool,status}` 和耗时 summary。`status` 是 `ok`、`denied` 或 `error`。
- `AuditedRunner` 接受可选的指标注册表和 `source`，记录运行计数、耗时和配额拒绝。MCP 传 `source="mcp"`，A2A 传 `source="a2a"`。
- MCP 的 `serve` 和 `serve-many` 加 `--metrics`。开启后包装 runner，并在 streamable-http 上暴露 `/metrics`。stdio 下只计数，没有端点。
- `build_http_app` 和 `run_http` 接受注册表，用 `server.custom_route("/metrics")` 注册端点，和 `/healthz` 同一种做法。
- A2A 暂时没有指标端点。

跨副本聚合不做。每个进程只渲染自己的计数，聚合交给抓取端，规则写在 `metrics.md`。

## 新增文件

- `tests/test_gateway_metrics.py`
- `tests/test_mcp_metrics.py`
- `tests/test_cli_mcp_metrics.py`
- `docs/contracts/metrics.md`
- `docs/evidence/SLICE-050-metrics-endpoints.txt`

## 修改文件

- `src/adk_agent/models/service.py`：`build_model_gateway_app(metrics=)`、`/metrics`、计数
- `src/adk_agent/tools/service.py`：`build_tool_gateway_app(metrics=)`、`/metrics`、计数
- `src/adk_agent/runtime/audit_proxy.py`：`metrics`、`source` 和运行计数
- `src/adk_agent/mcp/http.py`：`build_http_app`、`run_http` 的 `metrics`
- `src/adk_agent/mcp/server.py`：`serve_agent` / `serve_many` 的 `metrics` 和传递
- `src/adk_agent/a2a.py`：包装时传 `source="a2a"`
- `src/adk_agent/cli.py`：`serve` / `serve-many` 的 `--metrics`
- `docs/contracts/README.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
MetricsRegistry   # SLICE-047 已有
AuditedRunner(..., metrics: MetricsRegistry | None = None, source: str = "agent")
build_http_app(server, ..., metrics: MetricsRegistry | None = None)
serve_agent / serve_many(..., metrics: MetricsRegistry | None = None)
build_model_gateway_app(..., metrics: MetricsRegistry | None = None)
build_tool_gateway_app(..., metrics: MetricsRegistry | None = None)
```

网关默认创建注册表，默认暴露端点。MCP 只有传了注册表才包装和暴露。

指标：

```text
adk_agent_runs_total{source,tenant,agent,status}
adk_agent_run_duration_seconds{agent,tenant}
adk_agent_quota_denials_total{tenant,limit}
adk_model_calls_total{provider,status}
adk_model_call_duration_seconds{provider}
adk_tool_calls_total{tool,status}
adk_tool_call_duration_seconds{tool}
```

## 完成判据（可执行）

- [x] 模型网关成功调用计数 -> `tests/test_gateway_metrics.py::test_model_gateway_counts_calls`
- [x] 模型网关拒绝计数 -> `tests/test_gateway_metrics.py::test_model_gateway_counts_denials`
- [x] 模型网关 `/metrics` 要 token -> `tests/test_gateway_metrics.py::test_model_metrics_require_token`
- [x] 工具网关成功和拒绝计数 -> `tests/test_gateway_metrics.py::test_tool_gateway_counts_calls`
- [x] 工具网关 `/metrics` 要 token -> `tests/test_gateway_metrics.py::test_tool_metrics_require_token`
- [x] MCP 工具调用计数 -> `tests/test_mcp_metrics.py::test_serve_many_counts_runs`
- [x] MCP 配额拒绝计数 -> `tests/test_mcp_metrics.py::test_serve_many_counts_quota_denials`
- [x] MCP `/metrics` 端点 -> `tests/test_mcp_metrics.py::test_mcp_metrics_endpoint`
- [x] MCP `/metrics` 要 token -> `tests/test_mcp_metrics.py::test_mcp_metrics_require_token`
- [x] CLI `serve --metrics` 转发 -> `tests/test_cli_mcp_metrics.py::test_serve_forwards_metrics`
- [x] 默认不开启 -> `tests/test_cli_mcp_metrics.py::test_metrics_default_off`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：模型网关 `GET /metrics` -> 当前 404
- [x] 反例 2：工具网关 `GET /metrics` -> 当前 404
- [x] 反例 3：`build_http_app(server, metrics=...)` -> 当前 `TypeError`
- [x] 反例 4：`serve --metrics` -> 当前 argparse 退出 2
- [x] 反例 5：MCP 工具调用后注册表为空 -> 当前没有指标包装

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。已加 `metrics.md`，并更新 `cli.md` 的 MCP、模型网关、工具网关三节。

## 5 问威胁建模（10 分钟）

1. **数据**：运行和调用计数、耗时、provider 和 tool 名、租户名。
2. **调用方**：抓取端（Prometheus 或同类）、运维。
3. **信任边界**：抓取端到各服务 HTTP。
4. **恶意输入最坏结果**：未鉴权抓取泄露租户和 agent 名；标签基数爆炸拖垮内存。缓解是端点全部走现有鉴权中间件，标签只来自服务端校验过的 provider、tool、agent 和租户，不来自请求文本。指标不含请求内容。
5. **失败是否泄露信息**：未鉴权返回 401，不带指标。指标渲染不含异常文本。

## 范围外

- 跨副本聚合。由抓取端做，应用不共享计数。
- A2A 的指标端点。
- 直方图和分位数。
- 指标标签的租户级过滤。`/metrics` 是运维接口。

## 证据

- 反例红: `docs/evidence/SLICE-050-metrics-endpoints.txt`，两个网关 `/metrics` 404，三个 builder 不认识 `metrics`，`serve --metrics` 退出 2，MCP 注册表为空
- 实现后绿: 同文件，37 passed；`check.py --fast` ALL PASS（581 passed, 9 skipped），`--full` ALL PASS
- 真实工具网关: 同文件，一次成功一次拒绝后 `/metrics` 出现 ok/denied 计数和耗时，未鉴权 401
- 真实 MCP: 同文件，`--metrics` 下调用一次后 `/metrics` 出现 `source="mcp"` 的运行计数和耗时，未鉴权 401
