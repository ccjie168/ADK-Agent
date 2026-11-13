# SLICE-054 模型调用熔断

状态: spec'd
依据: SLICE-032，SLICE-041，SLICE-050，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

provider 持续失败时，网关现在会一次次把请求打到同一个坏掉的后端。这一刀给每个 provider 加熔断器，失败到阈值就快速拒绝，过一段时间再探测。

- 新增 `CircuitBreaker`，三态：closed、open、half_open。连续失败达到阈值就打开，打开期间 `allow()` 返回 False。经过重置时间后进入 half_open，只放行一个探测。探测成功回到 closed，失败重新打开。
- 新增 `BreakerProvider`，实现 `ModelProvider` 端口，包在一个 provider 外面。短路时抛 `ModelUnavailable`，并给指标记一次短路。
- 模型网关服务把 `ModelUnavailable` 映射成 503 `{"error":"model_unavailable"}`。
- `serve-model-gateway` 新增 `--breaker-failures`（默认 5）和 `--breaker-reset`（默认 30 秒）。每个 provider 一个独立熔断器。两个参数必须大于 0。
- 控制台和 `/metrics` 所在的注册表同时传给熔断包装，记录 `adk_model_breaker_short_circuits_total{provider}`。

这一刀只做模型 provider。工具调用、Inbound 请求限流和半开状态的并发探测队列不在范围里。

## 新增文件

- `src/adk_agent/resilience.py`：`CircuitBreaker`
- `src/adk_agent/models/breaker.py`：`BreakerProvider`
- `tests/test_resilience.py`
- `tests/models/test_breaker_provider.py`
- `tests/models/test_service_breaker.py`
- `tests/test_cli_model_breaker.py`
- `docs/evidence/SLICE-054-model-circuit-breaker.txt`

## 修改文件

- `src/adk_agent/models/gateway.py`：`ModelUnavailable`
- `src/adk_agent/models/service.py`：503 映射、熔断短路计数
- `src/adk_agent/models/__init__.py`：导出
- `src/adk_agent/cli.py`：两个熔断参数和包装
- `docs/contracts/cli.md`、`docs/contracts/metrics.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
CircuitBreaker(failure_threshold=5, reset_seconds=30.0, clock=time.monotonic):
  allow() -> bool
  record_success() -> None
  record_failure() -> None
  state -> "closed" | "open" | "half_open"

BreakerProvider(inner, breaker, *, metrics=None):
  name, egress -> 委派给 inner
  complete(request):
    允许 -> inner.complete；成功 record_success；异常 record_failure 后原样抛出
    拒绝 -> 指标 +1，抛 ModelUnavailable
```

状态规则：

- closed：失败计数加一，达到阈值后转 open，记录打开时间。
- open：`now - opened_at >= reset_seconds` 时转 half_open 并放行一个探测，否则拒绝。
- half_open：只放行一个探测；成功转 closed 并清零，失败转 open 并刷新打开时间。

## 完成判据（可执行）

- [ ] 阈值前保持 closed -> `tests/test_resilience.py::test_closed_until_threshold`
- [ ] 达到阈值后 open -> `tests/test_resilience.py::test_opens_at_threshold`
- [ ] 重置前拒绝 -> `tests/test_resilience.py::test_rejects_before_reset`
- [ ] 重置后只放行一个探测 -> `tests/test_resilience.py::test_half_open_single_probe`
- [ ] 探测成功关闭 -> `tests/test_resilience.py::test_probe_success_closes`
- [ ] 探测失败重新打开 -> `tests/test_resilience.py::test_probe_failure_reopens`
- [ ] 成功清零失败计数 -> `tests/test_resilience.py::test_success_resets_failures`
- [ ] 熔断后不再调用 provider -> `tests/models/test_breaker_provider.py::test_short_circuits_after_threshold`
- [ ] 短路计数 -> `tests/models/test_breaker_provider.py::test_short_circuit_metric`
- [ ] 重置后恢复 -> `tests/models/test_breaker_provider.py::test_recovers_after_reset`
- [ ] 成功透传 -> `tests/models/test_breaker_provider.py::test_success_passes_through`
- [ ] 服务返回 503 -> `tests/models/test_service_breaker.py::test_gateway_returns_503_when_open`
- [ ] CLI 转发两个参数 -> `tests/test_cli_model_breaker.py::test_serve_forwards_breaker_settings`
- [ ] CLI 默认值 -> `tests/test_cli_model_breaker.py::test_breaker_defaults`
- [ ] CLI 拒绝非正值 -> `tests/test_cli_model_breaker.py::test_rejects_nonpositive_settings`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.resilience import CircuitBreaker` -> 当前 `ImportError`
- [ ] 反例 2：`from adk_agent.models.breaker import BreakerProvider` -> 当前 `ImportError`
- [ ] 反例 3：provider 连续失败后仍被调用 -> 当前没有熔断，确实继续调用
- [ ] 反例 4：`serve-model-gateway --breaker-failures 2` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/`。已改 `cli.md` 的模型网关一节和 `metrics.md` 的指标列表。

## 5 问威胁建模（10 分钟）

1. **数据**：provider 名、失败计数、熔断状态、指标。
2. **调用方**：模型网关、控制台、运维。
3. **信任边界**：网关到 provider。
4. **恶意输入最坏结果**：provider 慢失败拖垮网关；熔断器被一次坏请求永久打开；指标标签被用户输入污染。缓解是阈值和重置时间可配、half_open 探测恢复、标签只用服务端 provider 名。熔断只影响对应 provider，不影响策略拒绝。
5. **失败是否泄露信息**：503 只回 `model_unavailable`，不带 provider 错误详情。审计仍由 `PolicyModelGateway` 记 `ModelUnavailable` 类名，不含请求内容。

## 范围外

- 工具网关和 MCP 的熔断。
- Inbound 请求限流。仍留给入口层或后续切片。
- 半开状态的并发探测队列。当前只允许一个探测。
- 熔断状态的事件通知和 gauge。

## 证据

- 反例红: 待补
- 实现后绿: 待补
