# SLICE-043 MCP principal 注入

状态: gated
依据: ADR-0002 第 7 条，ADR-0007，SLICE-042

## 意图（要什么，不写怎么写）

把 OIDC token 的 `principal` 带进 MCP 的 agent 运行和会话归属。这一刀只改 OIDC 模式下的 streamable-http。

- OIDC 模式下，ADK 运行的用户 id 使用 token 的 `subject`，不再用固定的 `mcp_user`。
- 会话按 subject 隔离。两个 subject 即使共用一个连接，也不共享会话。
- 创建会话时把 `principal` 写进会话 state，键名是 `principal`，值是 `Principal` 的 JSON。agent 工具可以读 `tool_context.state["principal"]`。
- 静态 token 和未鉴权模式完全不变，仍用 `mcp_user`。
- 复用 ADK 的 `_run_agent`，通过 runner 代理替换 `user_id` 和会话服务。不复制 ADK 的运行循环。
- `serve_agent` 在 OIDC 的 HTTP 路径下改为复用 `serve_many` 的单 agent 形态，以获得同样的注入。stdio 和静态 HTTP 仍走 `to_mcp_server`。

这一刀不做 MCP 路径的审计事件、工具守卫和模型网关接入。这些是已有缺口。

## 新增文件

- `tests/test_mcp_principal.py`
- `docs/evidence/SLICE-043-mcp-principal.txt`

## 修改文件

- `src/adk_agent/mcp/server.py`：`_principal_from_ctx`、`_PrincipalRunner`、`_PrincipalSessionService`、按 subject 的会话状态、`serve_agent` 的 OIDC 路径
- `docs/contracts/cli.md`：MCP HTTP 鉴权一节改为说明 principal 注入
- `docs/specs/ROADMAP.md`

## 数据形状

```text
_PrincipalRunner:
  app_name: str
  session_service: _PrincipalSessionService
  run_async(*, user_id, ...) -> 内层 runner.run_async(user_id=principal.subject, ...)
  __getattr__ -> 内层 runner

_PrincipalSessionService:
  create_session(app_name, user_id, state=None, session_id=None)
    -> 内层 create_session(user_id=principal.subject, state={**(state or {}), "principal": ...})
  get_session / delete_session / list_sessions / get_user_state
    -> 用 principal.subject 替换 user_id
  append_event / flush -> 直接委派
```

每个 subject 一份 `sessions`、`created`、`reap_failures`、`locks`。连接键仍用 ADK 的 `_connection_key`。

## 完成判据（可执行）

- [x] 从 ctx 读到 principal -> `tests/test_mcp_principal.py::test_principal_from_ctx`
- [x] ctx 没有请求时返回 None -> `tests/test_mcp_principal.py::test_principal_from_ctx_without_request`
- [x] runner 代理把 user_id 换成 subject -> `tests/test_mcp_principal.py::test_runner_rewrites_user_id`
- [x] 会话服务把 user_id 换成 subject -> `tests/test_mcp_principal.py::test_session_service_rewrites_user_id`
- [x] 创建会话写入 principal state -> `tests/test_mcp_principal.py::test_create_session_injects_principal_state`
- [x] 删除会话用 subject -> `tests/test_mcp_principal.py::test_delete_session_uses_subject`
- [x] 清理孤儿会话用 subject -> `tests/test_mcp_principal.py::test_reap_uses_subject`
- [x] 同一 subject 复用会话，不同 subject 不共享 -> `tests/test_mcp_principal.py::test_sessions_are_scoped_by_subject`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.mcp.server import _PrincipalRunner` -> 当前 `ImportError`
- [x] 反例 2：OIDC 模式下 agent 运行仍用 `mcp_user` -> 当前确实如此，期望用 token subject
- [x] 反例 3：两个 subject 共用一个连接 -> 当前共享会话，期望隔离
- [x] 反例 4：会话 state 里没有 `principal` -> 当前没有，期望有

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`，再改代码。

- OIDC 模式下，agent 运行的用户 id 是 token 的 `subject`。
- 会话按 subject 隔离，state 里有 `principal`。
- 静态和未鉴权模式仍用 `mcp_user`。

## 5 问威胁建模（10 分钟）

1. **数据**：JWT、principal、会话 state、agent 运行。
2. **调用方**：MCP host。
3. **信任边界**：host 到 MCP HTTP，issuer 的 JWKS 到服务。
4. **恶意输入最坏结果**：一个 subject 读到另一个 subject 的会话，或者 agent 工具读到伪造的 principal。缓解是会话按 subject 隔离，state 里的 principal 来自已验证 token，不是客户端输入。连接换 token 也不会复用别的 subject 的会话。
5. **失败是否泄露信息**：认证失败仍返回固定的 401 和 503。principal 只写进会话 state，不回显到错误里。

## 范围外

- MCP 路径的审计事件、工具守卫和模型网关接入。MCP 仍直接跑 ADK agent。
- A2A 和 stdio 的身份。
- ADK 运行循环的复制。代理依赖 ADK 的 `_run_agent` 和 `_connection_key`，升级 ADK 时需要复核。

## 证据

- 反例红: `docs/evidence/SLICE-043-mcp-principal.txt`，代理类不存在，1 个用例收集失败
- 实现后绿: 同文件，8 个目标测试通过，全量 458 passed 2 skipped，`check.py --full` ALL PASS，另做真实 MCP 双主体验证
