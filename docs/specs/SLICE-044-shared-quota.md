# SLICE-044 共享配额

状态: spec'd
依据: SLICE-041，SLICE-042，`docs/contracts/cli.md`，`docs/contracts/console.md`

## 意图（要什么，不写怎么写）

把 SLICE-041 的配额从单进程内存计数升级成多副本共享的后端，并接进控制台。

- 新增 `QuotaConfig`，按租户给 `QuotaPolicy`。只有列出的租户受限制，没列出的不限额。
- 新增 `PostgresQuotaManager`，实现既有的 `QuotaManager` 端口。多个控制台副本连同一个库时，`max_runs` 和 `max_concurrent` 是全局的，不是每副本一份。
- 新增 `build_quota_manager(url)`。`url` 为空返回 `InMemoryQuotaManager`，`postgresql://` 或 `postgresql+asyncpg://` 返回 `PostgresQuotaManager`，其他前缀抛 `QuotaStoreUnavailable`。缺少 `asyncpg` 也抛它。
- 控制台加 `--quota-config` 和 `QUOTA_URL`。聊天把 `quota` 和该租户的 `quota_policy` 传给 `AgentRuntime.run`，由运行时在模型调用前检查并写 `quota_exceeded` 审计。
- 非流式聊天配额用尽返回 429 `{"error":"quota_exceeded"}`。流式在 `event: error` 里给同样的错误。配额后端不可用返回 503 `{"error":"quota_unavailable"}`。
- 配额用尽和策略拒绝一样，不触发模型调用。

这一刀不做 MCP 路径的配额。MCP 直接跑 ADK agent，不经过 `AgentRuntime`，这是已知缺口。

## 新增文件

- `src/adk_agent/runtime/quota_postgres.py`：`PostgresQuotaManager`、`build_quota_manager`、`QuotaStoreUnavailable`
- `tests/runtime/test_quota_postgres.py`：Postgres 集成测试，无 `TEST_POSTGRES_URL` 时跳过
- `tests/runtime/test_quota_config.py`：配置解析
- `tests/test_console_quota.py`：控制台映射
- `docs/evidence/SLICE-044-shared-quota.txt`

## 修改文件

- `src/adk_agent/core/quota.py`：`QuotaConfig`
- `src/adk_agent/core/__init__.py`：导出 `QuotaConfig`
- `scripts/export_contracts.py`、`docs/contracts/quota_config.schema.json`
- `src/adk_agent/cli.py`：`console --quota-config`、`QUOTA_URL`
- `src/adk_agent/console.py`：`build_console_app(quota=, quota_config=)`、429 / 503 / 流式错误映射
- `docs/contracts/README.md`、`docs/contracts/cli.md`、`docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
QuotaConfig:
  tenants: dict[str, QuotaPolicy]        # 键非空，值为带至少一个上限的策略

PostgresQuotaManager:
  dsn: str                               # postgresql:// 或 postgresql+asyncpg://
  clock: Callable[[], float] = time.time # 跨进程必须用墙钟
  lease_seconds: float = 300.0           # 并发租约的存活上限，兜住崩溃副本
  reserve(tenant, policy) -> 异步上下文管理器

表 adk_quota_runs:
  tenant text, ran_at double precision   # 每个已占用的运行槽一行
  索引 (tenant, ran_at)

表 adk_quota_leases:
  lease_id text primary key, tenant text, expires_at double precision
  索引 (tenant, expires_at)
```

进入配额的事务步骤：

1. `pg_advisory_xact_lock(hashtext('adk_quota'), hashtext(tenant))`，同租户跨副本串行。
2. 删除该租户 `expires_at <= now` 的租约，回收崩溃副本留下的槽。
3. 有 `max_runs` 时，删除 `ran_at <= now - window_seconds` 的行，数剩余行。达到上限抛 `QuotaExceeded(tenant, "max_runs")`，否则插入一行。
4. 有 `max_concurrent` 时，数该租户未过期租约。达到上限抛 `QuotaExceeded(tenant, "max_concurrent")`，否则插入一条 `lease_id=uuid4().hex`、`expires_at=now+lease_seconds` 的租约。
5. 提交。超限时整笔回滚，所以先占的运行槽不会被消费，与内存实现的语义一致。

退出时按 `lease_id` 删除租约。没有 `max_concurrent` 时不写租约。

## 完成判据（可执行）

- [ ] 租户键为空被拒 -> `tests/runtime/test_quota_config.py::test_empty_tenant_rejected`
- [ ] 缺省不限额 -> `tests/runtime/test_quota_config.py::test_unlisted_tenant_is_unlimited`
- [ ] 空 URL 返回内存实现 -> `tests/runtime/test_quota_postgres.py::test_build_in_memory`
- [ ] 非 Postgres 前缀和缺驱动抛 `QuotaStoreUnavailable` -> `tests/runtime/test_quota_postgres.py::test_build_rejects_unknown_dsn`
- [ ] 两个管理器共享运行上限 -> `tests/runtime/test_quota_postgres.py::test_run_limit_is_shared`
- [ ] 窗口过期后放行 -> `tests/runtime/test_quota_postgres.py::test_window_expiry`
- [ ] 两个管理器共享并发上限 -> `tests/runtime/test_quota_postgres.py::test_concurrent_limit_is_shared`
- [ ] 退出时释放并发槽 -> `tests/runtime/test_quota_postgres.py::test_release_on_exit`
- [ ] 崩溃副本的租约过期后回收 -> `tests/runtime/test_quota_postgres.py::test_expired_lease_is_reclaimed`
- [ ] 并发被拒时不消费运行槽 -> `tests/runtime/test_quota_postgres.py::test_denied_concurrency_does_not_consume_run`
- [ ] 租户隔离 -> `tests/runtime/test_quota_postgres.py::test_tenants_are_isolated`
- [ ] 控制台超限返回 429 -> `tests/test_console_quota.py::test_chat_quota_exceeded`
- [ ] 控制台超限写 `denied` 审计 -> `tests/test_console_quota.py::test_quota_denial_is_audited`
- [ ] 流式超限发出错误事件 -> `tests/test_console_quota.py::test_stream_quota_exceeded`
- [ ] 未列出的租户不限额 -> `tests/test_console_quota.py::test_unlisted_tenant_unlimited`
- [ ] 配额后端不可用返回 503 -> `tests/test_console_quota.py::test_quota_store_unavailable`
- [ ] `console --quota-config` 文件缺失退出 1 -> `tests/test_cli_quota.py::test_quota_config_missing_file`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.runtime.quota_postgres import PostgresQuotaManager` -> 当前 `ImportError`
- [ ] 反例 2：`console --quota-config FILE` -> 当前 argparse 退出 2，不认识该参数
- [ ] 反例 3：配置 `max_runs=1` 后连发两次聊天 -> 当前两次都 200，期望第二次 429
- [ ] 反例 4：两个 `PostgresQuotaManager` 连同一个库，`max_runs=1`，各保留一次 -> 当前没有共享实现，期望第二次 `QuotaExceeded`
- [ ] 反例 5：没有 `asyncpg` 时 `build_quota_manager("postgresql://...")` -> 当前没有该函数，期望 `QuotaStoreUnavailable`

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。已改：

- `quota_config.schema.json`：`QuotaConfig`。
- `cli.md`：`console --quota-config FILE`、`QUOTA_URL`，缺驱动退出 1。
- `console.md`：`/api/chat` 的 429 `quota_exceeded`、`/api/chat/stream` 的错误事件。

补充到 `console.md`：配额后端不可用时 503 `{"error":"quota_unavailable"}`。

## 5 问威胁建模（10 分钟）

1. **数据**：按租户的运行计数和并发租约，DSN，`QuotaConfig`。
2. **调用方**：控制台副本、运维。
3. **信任边界**：控制台到 Postgres，配置文件到进程。
4. **恶意输入最坏结果**：并发副本超发，让租户突破上限；租户名注入 SQL；崩溃副本永久占住并发槽。缓解是每租户事务级 advisory lock、参数化 SQL、租约 TTL。配额配置只能收紧，不能绕过库里的全局计数。DSN 不写进日志或错误响应。
5. **失败是否泄露信息**：后端不可用返回固定 503，不区分连不上还是查询失败。429 只回 `quota_exceeded`，不带租户或上限数值。

## 范围外

- MCP 路径的配额。MCP 不经过 `AgentRuntime`。
- Redis 或其他后端。
- 配额配置的热更新和管理 API。
- 网关层的分布式限流。
- 运行历史跨副本聚合。

## 证据

- 反例红: 待补
- 实现后绿: 待补
