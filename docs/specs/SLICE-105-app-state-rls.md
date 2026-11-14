# SLICE-105 应用级状态租户 RLS

状态: gated
依据: ADR-0020 第 1 至 6 条。

## 意图（要什么，不写怎么写）

把 `app_states` 纳入会话侧的租户边界。开启 `--session-rls` 后，ADK 会话服务看到的 `app_name` 是 `<tenant>:<agent>`，`app_states` 的策略按这个前缀匹配，跨租户读 0 行、写被拒绝。不改 agent 名、审计目标或 manifest。

- `SESSION_TABLES` 从三张变四张，`app_states` 用 `app_name` 前缀策略，另外三张继续用 `user_id` 前缀。
- 会话服务 wrapper 在每次调用时改写 `app_name`。租户取自已认证 principal。
- `sessions enable-rls` 与启动检查覆盖四张表。
- 现有会话与 `app_states` 在开启后不可见，不自动迁移。

## 新增文件

- `docs/specs/SLICE-105-app-state-rls.md`
- `docs/evidence/SLICE-105-app-state-rls.txt`

## 修改文件

- `src/adk_agent/runtime/session_rls.py`（四张表、按表选策略表达式）
- `src/adk_agent/runtime/sessions.py`（`scoped_app_name`、`AppNameScopedSessionService`、`build_session_service` 接线）
- `tests/runtime/test_session_rls.py`（新增应用级状态的实测）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`（完成时）

## 数据形状

```text
policy:
  sessions, events, user_states:
    split_part(user_id, ':', 1) = current_setting('app.tenant_id', true)
  app_states:
    split_part(app_name, ':', 1) = current_setting('app.tenant_id', true)

session service wrapper:
  create_session(app_name="agent")  -> app_name="acme:agent"
  get_session(app_name="agent")     -> app_name="acme:agent"
  no tenant context                 -> app_name unchanged, RLS returns 0 rows

agent name surfaces unchanged:
  console agent lookup, manifest id, audit target, registry ref
```

## 完成判据（可执行）

- [x] 四张表都有策略，`app_states` 用 `app_name` -> `tests/runtime/test_session_rls.py::test_setup_creates_policies`
- [x] 开启后 `create_session` 落库的 `app_name` 是 `<tenant>:<agent>` -> `::test_app_name_is_scoped`
- [x] 跨租户读 `app_states` 返回 0 行 -> `::test_cross_tenant_app_state_is_invisible`
- [x] 别的租户前缀写入被 `WITH CHECK` 拒绝 -> `::test_app_state_write_is_rejected`
- [x] legacy 无前缀 `app_name` 不可见 -> `::test_legacy_app_state_is_invisible`
- [x] `sessions enable-rls` 覆盖四张表且幂等 -> `::test_enable_rls_is_idempotent`
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：当前 `SESSION_TABLES` 只有三张，`app_states` 没有策略 -> `test_setup_creates_policies` 失败
- [x] 反例 2：当前 wrapper 不改 `app_name` -> `test_app_name_is_scoped` 失败
- [x] 反例 3：装策略前跨租户能读到 `app_states` -> 负向对照

## 契约（如涉及对外接口）

`docs/contracts/cli.md` 的「会话存储的租户 RLS」已加入四张表、`app_name` 前缀与不可迁移说明，先于实现。

## 5 问威胁建模（10 分钟）

1. **数据**：`app_states` 的应用级状态，以及会话/事件/用户状态。
2. **调用方**：控制台、MCP、A2A、直接用应用角色连库的运维脚本。
3. **信任边界**：principal 到会话调用，服务到事务，应用角色到行。
4. **恶意输入最坏结果**：传别的租户的 `app_name`（缓解：租户取 principal，wrapper 改写，策略匹配前缀）；应用级状态含租户敏感数据（缓解：RLS 隔离）；用 plain `app_name` 直写（缓解：`WITH CHECK` 拒绝）；superuser（绕过 RLS，角色要求与 runbook 覆盖）。
5. **失败是否泄露信息**：错误不回显 DSN；拒绝表现为空结果或策略错误。

## 范围外

- 每租户数据库或 schema。
- legacy 会话与应用级状态的自动迁移。
- SQLite 与内存存储。

## 证据

- 反例红：`docs/evidence/SLICE-105-app-state-rls.txt` 的 red 段
- 实现后绿与 Postgres 实测：同文件 green 与 postgres 段
- 门禁：同文件 gate 段
