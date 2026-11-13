# SLICE-058 入口限流

状态: planned
依据: SLICE-050，SLICE-054，`docs/contracts/cli.md`，`docs/contracts/metrics.md`。

## 意图（要什么，不写怎么写）

控制台、模型网关、工具网关和审计服务都没有入口速率限制。一个失控的调用方可以按任意速率打满模型调用、工具调用和审计写入。这一刀加一个进程内的固定窗口限流器，按调用方计数，超限返回 429。

- 新增 `src/adk_agent/ratelimit.py`：`RateLimit`、`FixedWindowLimiter`、`RateLimitMiddleware`。
- 计数键是 principal 的 `tenant:subject`，没有 principal 时用客户端地址。
- `--rate-limit N --rate-limit-window SECONDS` 加到四个服务。不给 `--rate-limit` 时不限流。
- 超限返回 429 `{"error":"rate_limited"}`，带 `Retry-After` 秒数。
- `/healthz` 免限流。鉴权在限流之前，未认证请求仍是 401。
- 拒绝计数写 `adk_http_rate_limited_total{surface}`。
- 限流器在进程内。多副本各算一份，跨副本限流交给入口网关。

## 新增文件

- `src/adk_agent/ratelimit.py`
- `tests/test_ratelimit.py`
- `docs/evidence/SLICE-058-ingress-rate-limit.txt`

## 修改文件

- `src/adk_agent/console.py`、`src/adk_agent/models/service.py`、`src/adk_agent/tools/service.py`、`src/adk_agent/audit/service.py`：`rate_limit` 参数与中间件
- `src/adk_agent/cli.py`：四个命令的 `--rate-limit` / `--rate-limit-window` 与校验
- `docs/contracts/cli.md`、`docs/contracts/metrics.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
RateLimit(limit: int > 0, window_seconds: float > 0)

FixedWindowLimiter(limit, window_seconds, *, clock=time.monotonic)
  check(key: str) -> float | None    # 允许返回 None，拒绝返回需要等待的秒数
  # 每个 key 保存窗口内的命中时间戳；过期命中在 check 时弹出

RateLimitMiddleware(app, *, limiter, surface, metrics=None, exempt=frozenset({"/healthz"}))
  # scope 为 http 且不在 exempt 时计数
  # key = "tenant:subject" 或 request.client.host
  # 拒绝: 429 {"error":"rate_limited"} + Retry-After: ceil(等待秒数, 最小 1)
```

## 完成判据（可执行）

- [ ] 窗口内允许到上限，之后拒绝 -> `tests/test_ratelimit.py::test_allows_up_to_limit`
- [ ] 拒绝时给出剩余等待秒数 -> `tests/test_ratelimit.py::test_retry_after_counts_down`
- [ ] 窗口过去后重新放行 -> `tests/test_ratelimit.py::test_window_resets`
- [ ] 不同 key 互不影响 -> `tests/test_ratelimit.py::test_keys_are_isolated`
- [ ] 中间件返回 429、`Retry-After` 和固定文案 -> `tests/test_ratelimit.py::test_middleware_denies`
- [ ] 有 principal 时按 `tenant:subject` 计数 -> `tests/test_ratelimit.py::test_middleware_keys_by_principal`
- [ ] `/healthz` 免限流 -> `tests/test_ratelimit.py::test_healthz_is_exempt`
- [ ] 拒绝计数进入指标 -> `tests/test_ratelimit.py::test_rate_limited_metric`
- [ ] 未认证请求先 401 而不是 429 -> `tests/test_ratelimit.py::test_auth_runs_before_limit`
- [ ] 模型网关接入 -> `tests/test_ratelimit.py::test_model_gateway_wired`
- [ ] 工具网关接入 -> `tests/test_ratelimit.py::test_tool_gateway_wired`
- [ ] 控制台接入 -> `tests/test_ratelimit.py::test_console_wired`
- [ ] 审计服务接入 -> `tests/test_ratelimit.py::test_audit_wired`
- [ ] 四个命令的非法参数退出 1 -> `tests/test_ratelimit.py::test_cli_rejects_bad_flags`
- [ ] 控制台把限流参数传进应用 -> `tests/test_ratelimit.py::test_console_cli_wires_rate_limit`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.ratelimit import FixedWindowLimiter` -> 当前 `ModuleNotFoundError`
- [ ] 反例 2：`console --rate-limit 0` -> 当前 argparse 退出 2（参数不存在）
- [ ] 反例 3：先发满额请求再发一次，若无限流会得到 200/400 而不是 429 -> 由 `test_middleware_denies` 覆盖

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md`（四个命令和「入口限流」一节）与 `docs/contracts/metrics.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：principal 的 tenant 和 subject 作为计数键，客户端地址作为兜底键。
2. **调用方**：控制台用户、网关调用方、审计服务调用方。
3. **信任边界**：HTTP 入口到服务。计数键来自鉴权结果，不接受请求体里的声明值。
4. **恶意输入最坏结果**：伪造 tenant/subject 绕过限流（缓解：键来自 token 解析，不来自请求体）；大量不同 key 撑爆内存（缓解：每个 key 的队列长度不超过 limit，空窗口在字典过大时回收）；慢客户端占住连接（本轮不解决，见范围外）。参数为 0 或负数会让所有请求被拒或限流失效，CLI 拒绝。
5. **失败是否泄露信息**：429 只回固定文案和等待秒数，不回剩余额度或其他调用方的键。

## 范围外

- 跨副本共享计数。需要时接 Redis 或入口网关。
- MCP 和 A2A 端点。它们由 ADK 构建应用，留给后续切片。
- 连接数限制、请求体大小、慢客户端超时。
- 按路由或 agent 的差异化限流。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
