# SLICE-084 跨副本限流

状态: merged
依据: ADR-0012，SLICE-058，SLICE-059。

## 意图（要什么，不写怎么写）

进程内限流在副本扩容后按副本数放大。这一刀按 ADR-0012 加 Redis 共享计数，未配置时行为不变。

- `RedisFixedWindowLimiter`：按 surface 前缀与窗口起点建键，Lua 原子 `INCR` + `PEXPIRE`。
- `build_rate_limiter` 读 `RATE_LIMIT_URL`；未设置返回进程内实现。
- 中间件支持异步 `acheck`，同步实现保持兼容。
- Redis 不可达退进程内计数，记 `adk_rate_limit_backend_errors_total{surface}` 与一次 WARNING。
- 七个限流接线点统一改用 `build_rate_limiter`。
- 新增可选依赖 `redis`（`adk-agent[redis]`）。

## 新增文件

- `tests/test_ratelimit_redis.py`
- `docs/evidence/SLICE-084-shared-rate-limit.txt`

## 修改文件

- `src/adk_agent/ratelimit.py`
- `src/adk_agent/a2a.py`、`audit/service.py`、`console.py`、`mcp/http.py`、`models/service.py`、`registry/service.py`、`tools/service.py`
- `pyproject.toml`
- `docs/contracts/cli.md`、`docs/contracts/metrics.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
RATE_LIMIT_URL unset -> FixedWindowLimiter（进程内）
RATE_LIMIT_URL set   -> RedisFixedWindowLimiter
键: adk:rl:<surface>:<caller>:<window_start>
TTL: 窗口毫秒数，首次 INCR 时设置
failure: fallback.check(key) + backend error metric + 一次 WARNING
```

## 完成判据（可执行）

- [x] 两个限流器共享计数 -> `tests/test_ratelimit_redis.py::test_redis_limiter_counts_shared`
- [x] 故障退回进程内 -> `::test_redis_limiter_fail_open`
- [x] 故障计数 -> `::test_backend_error_metric`
- [x] 中间件等待异步限流器 -> `::test_middleware_awaits_async_limiter`
- [x] 环境变量选择后端 -> `::test_build_rate_limiter_selects_backend`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.ratelimit import RedisFixedWindowLimiter` -> 当前 `ImportError`
- [x] 反例 2：`RATE_LIMIT_URL` 被忽略 -> 当前无此配置

## 契约（如涉及对外接口）

已改 `docs/contracts/cli.md` 与 `docs/contracts/metrics.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：调用方键、窗口计数、后端错误。
2. **调用方**：所有 HTTP 入口。
3. **信任边界**：应用进程到 Redis。
4. **恶意输入最坏结果**：键注入到 Redis 命名空间（缓解：键只由租户/主体或客户端地址与 surface 组成，前缀固定）；缓存故障导致全站拒绝（缓解：fail-open 回退）；窗口边界放大（固定窗口固有，记录为已知限制）。
5. **失败是否泄露信息**：错误只进日志与计数，不返回调用方。

## 范围外

- 滑动窗口、令牌桶。
- Redis 高可用与认证（由部署方配置 URL）。
- 跨区域限流。

## 证据

- 反例红: `docs/evidence/SLICE-084-shared-rate-limit.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，两个网关进程共享一个 Redis，故障回退验证
