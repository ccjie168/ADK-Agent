# SLICE-103 会话存储租户 RLS

状态: gated
依据: ADR-0019 第 1 至 6 条。

## 意图（要什么，不写怎么写）

把会话的租户隔离从应用层约定变成 Postgres 强制。打开后，错误的 `user_id`、缺少请求上下文的调用、直接用应用角色查库，都读不到别的租户的行。不改 ADK 的 schema 形状，不改会话语义，不新增依赖。

- `sessions`、`events`、`user_states` 启用并强制 RLS，策略用 `split_part(user_id, ':', 1)` 匹配 `current_setting('app.tenant_id', true)`。
- 租户取自已认证 principal，不从 `user_id` 参数取。运行路径用 `current_invocation().principal.tenant`，运行外的控制台与 MCP 调用点设置请求上下文。
- 每个事务在 `after_begin` 时 `set_config`。没有租户时不设置，RLS 返回 0 行。
- `--session-rls` 只在 Postgres `SESSION_URL` 加 `--session-tenant-scope` 时可用。
- `adk-agent sessions enable-rls --database-url URL` 显式安装策略；启动只检查，不自动 DDL。

## 新增文件

- `src/adk_agent/runtime/session_rls.py`
- `tests/runtime/test_session_rls.py`
- `docs/evidence/SLICE-103-session-rls.txt`

## 修改文件

- `src/adk_agent/runtime/sessions.py`（`rls` 参数、事件安装、非 Postgres 拒绝）
- `src/adk_agent/console.py`（会话调用点设置租户上下文）
- `src/adk_agent/mcp/server.py`（`_PrincipalSessionService` 设置租户上下文）
- `src/adk_agent/cli.py`（`--session-rls`、启动检查、`sessions enable-rls`）
- `tests/test_cli_session_rls.py`（CLI 负向与命令）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`（完成时）

## 数据形状

```text
contextvar: session_tenant: str | None
  set by: console chat/list handlers, MCP _PrincipalSessionService, current_invocation fallback

SQLAlchemy event on DatabaseSessionService.db_engine.sync_engine:
  after_begin -> SELECT set_config('app.tenant_id', <tenant>, true)
  no tenant -> no statement

policy per table (sessions, events, user_states):
  USING      (split_part(user_id, ':', 1) = current_setting('app.tenant_id', true))
  WITH CHECK (split_part(user_id, ':', 1) = current_setting('app.tenant_id', true))

CLI:
  console | serve | serve-many  --session-rls  (requires --session-tenant-scope)
  sessions enable-rls --database-url URL
```

## 完成判据（可执行）

- [x] 非 Postgres 会话存储打开 `rls=True` 抛错 -> `tests/runtime/test_session_rls.py::test_rls_requires_postgres`
- [x] `--session-rls` 缺少 `--session-tenant-scope` 退出 1 -> `tests/test_cli_session_rls.py::test_rls_requires_tenant_scope`
- [x] 策略 DDL 对三张表执行 `ENABLE`/`FORCE ROW LEVEL SECURITY` 并建 `USING` 与 `WITH CHECK` -> `::test_setup_creates_policies`
- [x] 跨租户读返回 `None` -> `::test_cross_tenant_read_returns_none`（需要 `TEST_POSTGRES_URL`）
- [x] 没有租户上下文时读返回 `None` -> `::test_missing_tenant_reads_nothing`
- [x] 无冒号前缀的 legacy `user_id` 不可见 -> `::test_unscoped_user_id_is_invisible`
- [x] 非属主角色安装策略失败 -> `::test_enable_rls_requires_table_owner`
- [x] `sessions enable-rls` 幂等 -> `::test_enable_rls_is_idempotent`
- [x] 启动检查在策略缺失时失败，安装后通过 -> `::test_verify_rls`
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：`pytest tests/runtime/test_session_rls.py -q` -> 模块不存在，收集失败
- [x] 反例 2：`adk-agent serve --agent examples/minimal/agent.py --session-rls --transport stdio` -> 当前 `--session-rls` 未定义，退出 2
- [x] 反例 3：`adk-agent sessions enable-rls --database-url "$TEST_POSTGRES_URL"` -> 当前没有 `sessions` 命令，退出 2

## 契约（如涉及对外接口）

`docs/contracts/cli.md` 已加入「会话存储的租户 RLS」与 `sessions enable-rls` 两节，先于实现。

## 5 问威胁建模（10 分钟）

1. **数据**：会话、事件、用户状态；`app_states` 不在范围。
2. **调用方**：控制台、MCP、A2A、直接用应用角色连库的运维脚本。
3. **信任边界**：已认证 principal 到会话调用，会话服务到数据库事务，数据库角色到行。
4. **恶意输入最坏结果**：传别的租户的 `user_id`（缓解：租户取 principal，RLS 只按设置匹配，读到 0 行）；遗漏上下文（缓解：失败关闭）；应用角色直连（缓解：RLS 加非属主/非 superuser 要求）；superuser 或 `BYPASSRLS`（缓解：启动与安装命令拒绝；superuser 永远绕过，必须在 runbook 写明）；`app_states` 跨租户共享（已知范围外，禁用租户敏感应用状态）。
5. **失败是否泄露信息**：错误不回显 DSN；RLS 拒绝表现为空结果，不暴露行是否存在。

## 范围外

- `app_states` 的租户隔离，另起 ADR。
- 每租户数据库或 schema。
- legacy 无前缀会话的自动迁移。
- SQLite 与内存存储的 RLS。

## 证据

- 反例红：`docs/evidence/SLICE-103-session-rls.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- Postgres 实测：同文件 postgres 段
