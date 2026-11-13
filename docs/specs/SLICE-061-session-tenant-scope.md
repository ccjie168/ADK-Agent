# SLICE-061 会话按租户隔离（可选）

状态: merged
依据: SLICE-034，SLICE-040，SLICE-043，`docs/contracts/cli.md`，`docs/contracts/console.md`。

## 意图（要什么，不写怎么写）

ADK 的会话存到共享库时按 `(app_name, user_id, session_id)` 定位。控制台和 MCP 都用 `subject` 当 `user_id`，两个租户里同名的 subject 会落到同一个会话命名空间，互相能读到对方的会话。ADK 不提供租户列，也不接受注入 `app.tenant_id`，但 `user_id` 由我们的代码决定，这就是缝。

- 新增 `scoped_user_id(principal) -> "<tenant>:<subject>"`。
- 控制台和 MCP 增加 `--session-tenant-scope` 开关。打开后会话键用 `scoped_user_id`，关闭时保持 `subject`。
- 默认关闭，因为开启会让已存在的会话按旧键留在库里、不再出现在列表里，等于让所有用户重开会话。这是部署决定，不是默认行为。
- MCP 只在 OIDC 模式下有 principal，开关也只在那里生效；静态 token 和 stdio 不变。
- 不改 ADK 的表结构和查询。

## 新增文件

- `tests/test_session_tenant_scope.py`
- `docs/evidence/SLICE-061-session-tenant-scope.txt`

## 修改文件

- `src/adk_agent/runtime/sessions.py`：`scoped_user_id`
- `src/adk_agent/console.py`：`session_tenant_scope` 参数与四个会话调用点
- `src/adk_agent/mcp/server.py`：`_PrincipalSessionService`、`_PrincipalRunner`、按 principal 的会话缓存和 `serve_agent` / `serve_many` 参数
- `src/adk_agent/cli.py`：三个命令的 `--session-tenant-scope`
- `docs/contracts/cli.md`、`docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
scoped_user_id(principal) -> f"{principal.tenant}:{principal.subject}"

console(session_tenant_scope=True):  session user_id = scoped_user_id(caller)
console(session_tenant_scope=False): session user_id = caller.subject
mcp    (session_tenant_scope=True):  代理把所有 user_id 改写成 scoped_user_id(principal)
                                     per-principal 会话缓存也用这个键
```

## 完成判据（可执行）

- [x] 会话键是 `tenant:subject` -> `tests/test_session_tenant_scope.py::test_scoped_user_id`
- [x] 打开开关后同名 subject 跨租户会话互不可见 -> `tests/test_session_tenant_scope.py::test_console_isolates_tenants`
- [x] 关闭开关时保持 subject 行为 -> `tests/test_session_tenant_scope.py::test_console_default_keeps_subject`
- [x] 列表接口按开关过滤 -> `tests/test_session_tenant_scope.py::test_console_lists_own_tenant_only`
- [x] MCP 代理改写为 `tenant:subject` -> `tests/test_session_tenant_scope.py::test_mcp_proxy_scopes_user_id`
- [x] MCP 代理默认保持 subject -> `tests/test_session_tenant_scope.py::test_mcp_proxy_default_subject`
- [x] 控制台 CLI 透传开关 -> `tests/test_session_tenant_scope.py::test_console_cli_wires_flag`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.runtime.sessions import scoped_user_id` -> 当前 `ImportError`
- [x] 反例 2：`console --session-tenant-scope` -> 当前 argparse 退出 2（参数不存在）
- [x] 反例 3：`build_console_app(..., session_tenant_scope=True)` -> 当前 `TypeError`

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md`（console、serve/serve-many）与 `docs/contracts/console.md`（`/api/sessions`）。

## 5 问威胁建模（10 分钟）

1. **数据**：会话 id、会话 state（含 principal）、会话事件。
2. **调用方**：控制台用户和 MCP 调用方。
3. **信任边界**：token 里的 tenant 与 subject 到共享会话库。
4. **恶意输入最坏结果**：同名 subject 跨租户共享会话（现状）。缓解是可选开关，键里带 tenant。开关默认关闭，误开只是让旧会话不可见，不泄露数据；误关则维持现状。subject 里的分隔符不会造成歧义吗？tenant 和 subject 都来自 token，`:` 出现在 tenant 中会与 subject 拼接产生歧义键，但没有跨租户一致的键可对齐，不会互相读到；这一点在范围外说明。
5. **失败是否泄露信息**：列表只返回当前键下的会话 id 和时间，不含 state 和 events。

## 范围外

- 数据库级租户列和 RLS。ADK 生成的查询不可注入。
- 自动迁移已有会话到新键。
- `tenant` 或 `subject` 含 `:` 时的编码方案。
- A2A 会话（固定租户 `local`）。

## 证据

- 反例红: `docs/evidence/SLICE-061-session-tenant-scope.txt` 的 red 段
- 实现后绿: 同文件 green 段，7 个新用例与全量 711 个用例通过
- 实机: 同文件 live 段。真控制台加 SQLite 会话库，默认写入 `console_user`；打开开关后写入 `local:console_user`，列表只显示后者，旧键会话不可见
