# ADR-0020 应用级状态的租户隔离

状态: Accepted   日期: 2026-11-15   签字: Jie CAO（会话确认）

## 背景

ADR-0019 用 Postgres RLS 隔离了 `sessions`、`events`、`user_states`，租户从 `user_id` 前缀取。`app_states` 没有跟进，因为它的主键只有 `app_name`，没有 `user_id` 维度。

```text
sessions      (app_name, user_id, id)
events        (id, app_name, user_id, session_id)
user_states   (app_name, user_id)
app_states    (app_name)
```

ADK 的 `app:` 状态写在 `app_states`。同一 agent 名在不同租户下运行时，两个租户共享同一行。只要某个 agent 把租户敏感的数据放进应用级状态，就会跨租户泄露。这是会话侧最后一块已知缺口。

## 决定

1. **`app_states` 启用并强制 RLS，租户从 `app_name` 前缀取。** 策略：

   ```sql
   split_part(app_name, ':', 1) = current_setting('app.tenant_id', true)
   ```

   `USING` 与 `WITH CHECK` 都要。

2. **开启 `--session-rls` 时，会话服务的 `app_name` 变成 `<tenant>:<agent>`。** 租户取自已认证 principal，复用 ADR-0019 的上下文。会话服务 wrapper 在每次调用时改写 `app_name`；`append_event` 用的是已带前缀的 `Session`，不再改写。

3. **另外三张表继续按 `user_id` 隔离。** `app_name` 前缀对它们是冗余的一致性措施，不改变 ADR-0019 的策略。

4. **`sessions enable-rls` 安装第四张表的策略，启动检查一并验证。** `SESSION_TABLES` 从三张变四张，`verify_session_rls` 对 `app_states` 用 `app_name` 条件，对另外三张用 `user_id` 条件。

5. **控制台、MCP、审计、manifest 里的 agent 名不变。** 只有 ADK 会话服务看到的 `app_name` 带前缀。agent 查找、`agent.run` 审计目标、注册表引用仍用原始名字。

6. **legacy 不自动迁移。** 没有前缀的 `app_states` 行不可见；已经按 `--session-tenant-scope` 存的会话也会因为 `app_name` 变化而读不到，需要迁移或丢弃。

## 切片

- SLICE-105 应用级状态 RLS。`app_name` 改写 wrapper、四张表的策略与检查、控制台与 MCP 接线、Postgres 集成测试（跨租户 app 状态读 0 行、写被 `WITH CHECK` 拒绝、缺租户 0 行、legacy 不可见）。
- SLICE-106 运维收口。runbook 增加第四张表、升级影响与迁移说明，证据记录跨进程验证。

契约与 CLI 的变更在 SLICE-105 开始前先进 `docs/contracts/`。

## 备选与否决

- **给 `app_states` 加 tenant 列并自定义查询。** 要 fork ADK 的 ORM、查询与迁移，升级风险高；否决。
- **每租户一个数据库或 schema。** 隔离最强，但连接路由与迁移扇出重；v1 否决，和 ADR-0019 一致。
- **禁止应用级状态。** 租户敏感数据可以不放，但 ADK 的 `app:` 状态是公开能力，运行时很难可靠拦截；否决。
- **只给 `app_states` 加策略，不改 `app_name`。** 没有可用的租户列，策略无法判定租户；否决。
- **在应用层做键前缀，不开 RLS。** 挡不住查询 bug 与直连；否决。

## 后果

- 会话侧四张表都由数据库强制租户边界。
- 开启后 `app_name` 变化，现有会话与 `app_states` 都不可见。升级前要先决定迁移或接受丢弃。
- 会话键从 `(app_name, user_id, id)` 变成 `(<tenant>:<app_name>, <tenant>:<subject>, id)`，租户维度出现两次，属于一致性冗余，不是错误。
- 依赖 ADK 会话服务把 `app_name` 原样传给四张表。升级 ADK 时复核 `create_session`、`get_session`、`list_sessions`、`delete_session`、`append_event`、`get_user_state` 的 `app_name` 用法。

## 确认记录

2026-11-15 草拟，同日确认三点：

1. 接受 `app_name` 前缀作为 `app_states` 的租户键，不新增 tenant 列。
2. 接受开启后 `app_name` 带前缀，现有会话与 `app_states` 需要迁移或丢弃。
3. 接受另外三张表继续按 `user_id` 隔离，`app_name` 前缀只作一致性措施。
