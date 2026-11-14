# ADR-0019 会话存储的租户隔离

状态: Accepted   日期: 2026-11-15   签字: Jie CAO（会话确认）

## 背景

会话是平台里最后一块只靠应用层约定隔离的共享状态。

- ADK 的 `DatabaseSessionService` 把数据存在 `sessions`、`events`、`user_states`、`app_states`。前三张表的主键以 `(app_name, user_id, ...)` 开头，`app_states` 只有 `app_name`。
- SLICE-061 允许控制台与 MCP/A2A 传 `<tenant>:<subject>`，但这是可选项，默认仍是 `<subject>`。
- 这些 Postgres 表没有租户列，也没有 RLS。一次错误的 `user_id`、一个遗漏的调用点，或者直接用应用角色查库，都能读到别的租户的数据。
- 配额表在 SLICE-052 已经有 RLS 先例，策略是 `tenant = current_setting('app.tenant_id', true)`，事务内用 `set_config` 设置。

方向评审把会话隔离列为对外多租户的剩余硬缺口。这一刀只改隔离方式，不改会话语义、不改 ADK 的 schema 形状。

## 决定

1. **Postgres 会话表启用 RLS，租户从 `user_id` 前缀取。** 对 `sessions`、`events`、`user_states` 执行 `ENABLE ROW LEVEL SECURITY` 与 `FORCE ROW LEVEL SECURITY`，策略同时有 `USING` 与 `WITH CHECK`：

   ```sql
   split_part(user_id, ':', 1) = current_setting('app.tenant_id', true)
   ```

   `app_states` 没有 user_id 维度，v1 不覆盖，见范围外。

2. **每个事务设置 `app.tenant_id`。** 在 ADK 服务的 `db_engine.sync_engine` 上挂 SQLAlchemy `begin` 事件，执行 `SELECT set_config('app.tenant_id', :tenant, true)`。租户来自已认证的 principal，存在请求上下文的 contextvar 里，运行路径回退到 `current_invocation().principal.tenant`。不从 `user_id` 参数取租户，那是调用方可控的数据；`user_id` 只用于行匹配。没有租户时事件不设置，RLS 以空结果失败关闭。

3. **RLS 与租户作用域绑定。** `--session-rls` 只在 `SESSION_URL` 是 Postgres 且 `--session-tenant-scope` 打开时可用；CLI 拒绝其他组合。SQLite 与内存存储保留给单机与演示，不承诺 RLS。

4. **策略由显式命令安装。** `adk-agent sessions enable-rls --database-url ...` 建策略。服务以 `--session-rls` 启动时检查策略存在，缺失就退出。不在启动时自动 DDL，避免多副本竞争和权限不明的执行者。

5. **DB 角色要求与配额表一致。** 角色必须是这三张表的属主，不能是 superuser，不能有 `BYPASSRLS`。策略安装命令与运行时用同一角色。

6. **legacy 不自动迁移。** 没有冒号前缀的 `user_id` 行在 RLS 下不可见。演示数据可以丢；生产数据要迁移得单独评审，不放进这一刀。

## 切片

- SLICE-103 会话 RLS 核心。`runtime/session_rls.py` 提供策略 DDL 与事件安装，会话服务 wrapper 在每次调用期间设置租户 contextvar，`build_session_service` 接线，CLI 增加 `--session-rls` 与 `sessions enable-rls`。Postgres 集成测试覆盖跨租户读返回 0 行、缺设置返回 0 行、未加前缀返回 0 行、非属主角色建策略失败。
- SLICE-104 运维收口。runbook 增加启用、回滚与角色要求，证据文件记录跨进程验证，契约补 CLI 与新错误码。

契约与 CLI 的变更在 SLICE-103 开始前先进 `docs/contracts/`。

## 备选与否决

- **每租户一个数据库或 schema。** 隔离最强，但要做连接路由、迁移按租户扇出、ADK 服务按租户实例化；v1 否决，留作强隔离客户的演进。
- **只靠应用层强制 `user_id`。** 这是现状。它挡不住查询 bug、遗漏的调用点，也挡不住直接用应用角色访问数据库；否决。
- **给 ADK 表加 tenant 列并自定义查询。** 要 fork ADK 的 ORM、查询与迁移，升级风险高；否决。
- **把 RLS 放在 `app_states`。** 它没有 user_id 维度，策略无法从现有列推导租户；v1 不做，另起 ADR 决定是否按租户拆分 `app_name`。
- **启动时自动建策略。** 多副本同时执行 DDL，且执行者权限说不清；否决，改显式命令。

## 后果

- 会话隔离从应用层约定变成数据库强制。错误调用与直连读都会得到空结果。
- 默认关闭。打开后旧会话不可见，需要迁移或丢弃。
- `app_states` 仍按 `app_name` 共享。租户敏感的应用级状态不能放那里，必须放会话或用户状态。
- 每个会话事务多一次 `set_config`，开销小；读写路径都受影响。
- ADK 懒创建会话表，策略安装要在表存在之后。`enable-rls` 在表不存在时报错，并提示先创建一次会话。
- 依赖 ADK 2.14 的 `DatabaseSessionService.db_engine` 属性与 `after_begin` 事件。升级 ADK 时复核这两点。

## 确认记录

2026-11-15 草拟，同日确认三点：

1. 接受 `user_id` 前缀作为行匹配键，不新增 tenant 列。更正：草稿曾把 `user_id` 前缀也写成租户事实来源，确认后改为以已认证 principal 为准。`user_id` 是调用方传入的数据，不能决定 `app.tenant_id`，否则传别人的 `user_id` 就能读到别人的行。
2. 接受 `app_states` 不在 v1 RLS 范围，租户敏感的应用级状态禁用。
3. 接受显式 `sessions enable-rls` 迁移命令，不在启动时自动 DDL。
4. 实现时发现 SQLAlchemy 2.1 的 `ConnectionEvents` 没有 `after_begin`，只有 ORM 的 `SessionEvents` 有。改用 `db_engine.sync_engine` 的 `begin` 事件，并在 SQLite 上验证过 `begin` 事件内可以执行 SQL。语义不变。
