# SLICE-052 配额表的行级隔离

状态: gated
依据: SLICE-044，SLICE-050

## 意图（要什么，不写怎么写）

配额表已经按 `tenant` 列过滤，但这条规则只活在应用代码里。任何一条漏写 `tenant` 的查询都会跨租户。这一刀在 Postgres 里把隔离做成约束。

- `PostgresQuotaManager` 的建表步骤给 `adk_quota_runs` 和 `adk_quota_leases` 打开并强制行级安全，每张表一条按 `tenant = current_setting('app.tenant_id', true)` 的策略，`USING` 和 `WITH CHECK` 都写。
- 每次预留事务在访问表之前执行 `SELECT set_config('app.tenant_id', $1, true)`，值是当前租户。事务结束后自动失效。
- 释放租约也在事务里设置同一个租户再删除。
- 策略和开关是幂等的：先 `DROP POLICY IF EXISTS`，再 `CREATE POLICY`。建表失败仍按 `QuotaStoreUnavailable` 处理。
- 没设置 `app.tenant_id` 时，策略返回零行，默认拒绝。

这条只保护配额表。ADK 管理的会话表不在范围里。

## 新增文件

- `tests/runtime/test_quota_rls.py`（需要 `TEST_POSTGRES_URL`）
- `docs/evidence/SLICE-052-quota-rls.txt`

## 修改文件

- `src/adk_agent/runtime/quota_postgres.py`：建表策略、`set_config`、释放路径带租户
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
adk_quota_runs(tenant, ran_at)      -- ENABLE + FORCE ROW LEVEL SECURITY
adk_quota_leases(lease_id, tenant, expires_at) -- ENABLE + FORCE ROW LEVEL SECURITY

policy adk_quota_runs_tenant:
  USING (tenant = current_setting('app.tenant_id', true))
  WITH CHECK (tenant = current_setting('app.tenant_id', true))
policy adk_quota_leases_tenant: 同形

预留事务:
  pg_advisory_xact_lock(...)
  set_config('app.tenant_id', tenant, true)
  之后才是租约清理、窗口计数、插入

释放:
  独立事务
  set_config('app.tenant_id', tenant, true)
  DELETE FROM adk_quota_leases WHERE lease_id = $1
```

## 完成判据（可执行）

- [x] 两张表都有租户策略 -> `tests/runtime/test_quota_rls.py::test_manager_enables_rls_policies`
- [x] 未设置租户时看不到运行行 -> `tests/runtime/test_quota_rls.py::test_runs_are_hidden_without_tenant_setting`
- [x] 设置其他租户时看不到运行行 -> 同测试
- [x] 未设置租户时看不到租约 -> `tests/runtime/test_quota_rls.py::test_leases_are_hidden_without_tenant_setting`
- [x] 强制 RLS 下配额仍按租户生效 -> `tests/runtime/test_quota_rls.py::test_manager_still_enforces_limits_under_rls`
- [x] 原有 Postgres 配额用例全绿 -> `tests/runtime/test_quota_postgres.py`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`pg_policies` 里没有配额表的策略 -> 当前为空
- [x] 反例 2：非超级用户不设 `app.tenant_id` 直接 `SELECT count(*)` -> 当前能看到租户 A 的行，期望 0
- [x] 反例 3：把 `app.tenant_id` 设成租户 B 再查租户 A 的行 -> 当前仍能看到，期望 0

## 契约（如涉及对外接口）

没有对外接口变化。数据库角色必须能 `ALTER TABLE` 和 `CREATE POLICY`，也就是表的属主；超级用户和 `BYPASSRLS` 角色不受策略约束，这一点写进文档。

## 5 问威胁建模（10 分钟）

1. **数据**：按租户的运行计数和并发租约。
2. **调用方**：配额管理器和直接 SQL 的运维。
3. **信任边界**：应用进程到 Postgres。
4. **恶意输入最坏结果**：一条漏写租户条件的查询读到别的租户的计数，或者写入别人的租户。缓解是数据库策略在 `USING` 和 `WITH CHECK` 两侧强制，默认拒绝，事务级设置租户，连接池不会把设置带到下一个事务。
5. **失败是否泄露信息**：策略拒绝表现为零行或约束错误，不返回别租户的数据。建表或策略失败抛 `QuotaStoreUnavailable`，不带 DSN。

## 范围外

- ADK 会话表的行级隔离。它的查询由 ADK 生成，无法注入租户设置。
- 连接池级别的角色切换。
- 审计和注册表的库表化。
- 超级用户和 `BYPASSRLS` 角色的约束。生产必须用非超级用户连接。

## 证据

- 反例红: `docs/evidence/SLICE-052-quota-rls.txt`，策略为空，未设置租户时运行行和租约都可见
- 实现后绿: 同文件，4 个 RLS 用例和原有 11 个 Postgres 配额用例全过；`check.py --fast` ALL PASS（594 passed, 13 skipped），`--full` ALL PASS
- 真实目录: 同文件，`pg_policies` 两条策略，两张表 `rowsecurity` 和 `forcerowsecurity` 都是 true
