# SLICE-059 MCP 与 A2A 入口限流

状态: merged
依据: SLICE-042，SLICE-048，SLICE-058，`docs/contracts/cli.md`，`docs/contracts/metrics.md`。

## 意图（要什么，不写怎么写）

SLICE-058 给控制台和三个独立服务加了限流，MCP streamable-http 和 A2A 端点仍然敞开。这两个入口直接暴露给其他 agent 和外部调用方，是残余风险最高的地方。这一刀把同一个限流中间件接上去。

- `build_http_app` 和 `run_http` 增加 `rate_limit`，surface 是 `mcp`。中间件在鉴权之前注册，鉴权仍在外层。
- `serve_agent`、`serve_many` 和 CLI 的 `serve` / `serve-many` 增加 `--rate-limit` / `--rate-limit-window`。限流只对 `streamable-http` 有意义，配 `stdio` 同时给 `--rate-limit` 退出 1。
- `/healthz` 和 `/metrics` 对 MCP 豁免。
- `build_a2a_app` 和 `serve_a2a` 增加 `rate_limit`，surface 是 `a2a`。A2A 没有健康检查和指标端点，所有路径都计数，按客户端地址。
- MCP 的 `/metrics` 存在时，拒绝计数写 `adk_http_rate_limited_total{surface="mcp"}`。A2A 不记录。

## 新增文件

- `tests/test_mcp_a2a_rate_limit.py`
- `docs/evidence/SLICE-059-mcp-a2a-rate-limit.txt`

## 修改文件

- `src/adk_agent/mcp/http.py`、`src/adk_agent/mcp/server.py`、`src/adk_agent/a2a.py`、`src/adk_agent/cli.py`
- `docs/contracts/cli.md`、`docs/contracts/metrics.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

复用 `RateLimit`、`FixedWindowLimiter`、`RateLimitMiddleware`，不新增类型。

```text
build_http_app(..., rate_limit=None)   # surface="mcp", exempt={"/healthz", "/metrics"}
build_a2a_app(..., rate_limit=None)    # surface="a2a", exempt=frozenset()
serve_agent / serve_many / serve_a2a / CLI 透传 rate_limit
```

## 完成判据（可执行）

- [x] MCP 请求超过上限返回 429 -> `tests/test_mcp_a2a_rate_limit.py::test_mcp_rate_limited`
- [x] MCP `/healthz` 和 `/metrics` 不计数 -> `tests/test_mcp_a2a_rate_limit.py::test_mcp_exempt_paths`
- [x] MCP 拒绝计数进入指标 -> `tests/test_mcp_a2a_rate_limit.py::test_mcp_metric`
- [x] MCP 未认证请求先 401 -> `tests/test_mcp_a2a_rate_limit.py::test_mcp_auth_precedes_limit`
- [x] A2A 请求超过上限返回 429 -> `tests/test_mcp_a2a_rate_limit.py::test_a2a_rate_limited`
- [x] A2A 未认证请求先 401 -> `tests/test_mcp_a2a_rate_limit.py::test_a2a_auth_precedes_limit`
- [x] `serve` / `serve-many` / `serve-a2a` 的非法参数退出 1 -> `tests/test_mcp_a2a_rate_limit.py::test_cli_rejects_bad_flags`
- [x] stdio 配 `--rate-limit` 退出 1 -> `tests/test_mcp_a2a_rate_limit.py::test_stdio_rejects_rate_limit`
- [x] 库调用 stdio 配限流抛 `ValueError` -> `tests/test_mcp_a2a_rate_limit.py::test_library_rejects_stdio_rate_limit`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`build_http_app(..., rate_limit=...)` -> 当前 `TypeError: unexpected keyword argument`
- [x] 反例 2：`build_a2a_app(..., rate_limit=...)` -> 当前 `TypeError`
- [x] 反例 3：`adk-agent serve --agent x --rate-limit 5` -> 当前 argparse 退出 2（参数不存在）

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md`（serve/serve-many、serve-a2a、「入口限流」）与 `docs/contracts/metrics.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：MCP 的 principal（OIDC 时）或客户端地址；A2A 的客户端地址；拒绝计数。
2. **调用方**：其他 agent、MCP 宿主、A2A 消费方。
3. **信任边界**：网络入口到 agent 运行。MCP 的键来自 OIDC token 解析结果。
4. **恶意输入最坏结果**：不设限时一个调用方按任意速率触发 agent 运行和审计写入。缓解是同一固定窗口限流器。stdio 没有网络对端，给 `--rate-limit` 直接报错，避免以为开了限流。
5. **失败是否泄露信息**：429 固定文案和等待秒数，不含调用方键。

## 范围外

- 跨副本共享计数。
- 按 MCP 工具名或 A2A 方法分别限流。
- stdio 传输的限流。

## 证据

- 反例红: `docs/evidence/SLICE-059-mcp-a2a-rate-limit.txt` 的 red 段
- 实现后绿: 同文件 green 段，12 passed，全量 690 passed
- 实机: 同文件 live 段。真 MCP 服务限 2 次每 30 秒，前两次 404，第三次 429（Retry-After 30），`/healthz` 与 `/metrics` 豁免，计数 2；真 A2A 服务限 1 次，第二次起 429，无 token 仍 401
