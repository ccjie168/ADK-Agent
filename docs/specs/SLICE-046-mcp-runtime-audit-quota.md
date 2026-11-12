# SLICE-046 MCP 运行路径接入审计与配额

状态: gated
依据: SLICE-027，SLICE-041，SLICE-043，SLICE-044，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

MCP 的 `serve` 和 `serve-many` 现在直接跑 ADK agent，不经过 `AgentRuntime`，所以没有 `agent.run` 审计，也不受租户配额约束。这一刀把这两件事补上，不复制 ADK 的运行循环。

- 新增 `_AuditedRunner`，包在给 `_run_agent` 的 runner 外面。进入前按租户预留配额，运行结束后写一条 `agent.run` 审计。
- 配额用尽时先写 `denied` 审计再抛 `QuotaExceeded`，agent 不运行。
- 运行异常写 `error` 审计，`error_code` 是异常类名，然后原样抛出。
- tenant 和 principal 来自 token。没有 principal 的模式用 `local` 租户和 `mcp_user` 主体。
- `serve` 和 `serve-many` 增加 `--audit-file`、`--audit-url`、`--audit-token-env`、`--quota-config`，复用模型网关的审计规则和控制台的配额装配。
- 配置了审计或配额时，`serve` 改用 `serve-many` 的单 agent 形态，让同一层包装生效。OIDC HTTP 路径原本就这么做。
- 没有配置审计和配额时行为不变，不创建包装。

这一刀不做 A2A 路径、工具调用级审计和 MCP 的 trace 树。

## 新增文件

- `src/adk_agent/mcp/runtime.py`：`AuditedMcpRunner`、`wrap_runner`
- `tests/test_mcp_runtime.py`
- `tests/test_mcp_runtime_wiring.py`
- `tests/test_cli_mcp_runtime.py`
- `docs/evidence/SLICE-046-mcp-runtime-audit-quota.txt`

## 修改文件

- `src/adk_agent/mcp/server.py`：`serve_agent` / `serve_many` 的 `audit`、`quota`、`quota_config` 参数和包装
- `src/adk_agent/mcp/__init__.py`：导出包装
- `src/adk_agent/cli.py`：两个 MCP 命令的审计和配额参数，配额装配复用控制台的 helper
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditedMcpRunner:
  inner: runner                # _PrincipalRunner 或原始 runner
  agent_name: str
  principal: Principal         # 无 token 时是 local/mcp_user/service
  input_text: str              # 本次工具调用的 request
  audit: AuditSink | None
  quota: QuotaManager | None
  quota_policy: QuotaPolicy | None

  run_async(**kwargs) -> 异步生成器
    - quota 和 policy 都有时，async with quota.reserve(tenant, policy)
    - 逐条透传 inner.run_async(**kwargs) 的事件，收集最终回复文本
    - 成功写 agent.run ok，带 result_hash
    - QuotaExceeded 写 denied / quota_exceeded 后抛出
    - 其他异常写 error / 异常类名后抛出
  app_name / session_service -> 委派给 inner
```

审计字段：

- `action="agent.run"`，`target=f"{agent_name}@dev"`，`agent_ref=dev_agent_ref(agent_name)`。
- `run_id` 和 `trace_id` 每次工具调用新生成。
- `args_hash=hash_text(input_text)`，成功时 `result_hash=hash_text(最终文本)`。
- `egress="none"`，`data_classes=[]`，`latency_ms` 从进入算到结束。

## 完成判据（可执行）

- [x] 成功运行写 ok 审计，带结果哈希 -> `tests/test_mcp_runtime.py::test_audits_ok_run`
- [x] 失败运行写 error 审计并原样抛出 -> `tests/test_mcp_runtime.py::test_audits_failed_run`
- [x] 配额用尽先写 denied 且不运行 agent -> `tests/test_mcp_runtime.py::test_quota_denial_skips_runner`
- [x] 未列出的租户不限额 -> `tests/test_mcp_runtime.py::test_unlisted_tenant_unlimited`
- [x] 无 principal 时用 local/mcp_user -> `tests/test_mcp_runtime.py::test_anonymous_uses_local_tenant`
- [x] 事件原样透传 -> `tests/test_mcp_runtime.py::test_events_pass_through`
- [x] 没配审计和配额时不写事件 -> `tests/test_mcp_runtime.py::test_no_sinks_is_passthrough`
- [x] `serve_many` 的工具调用带审计和配额 -> `tests/test_mcp_runtime_wiring.py::test_serve_many_wraps_tool`
- [x] `serve` 在配置审计时走 `serve_many` -> `tests/test_mcp_runtime_wiring.py::test_serve_agent_delegates_with_audit`
- [x] `serve` 在配置配额时走 `serve_many` -> `tests/test_mcp_runtime_wiring.py::test_serve_agent_delegates_with_quota`
- [x] 没配置时仍旧走 `to_mcp_server` -> `tests/test_mcp_runtime_wiring.py::test_serve_agent_keeps_default_path`
- [x] CLI `serve` 转发审计和配额 -> `tests/test_cli_mcp_runtime.py::test_serve_forwards_audit_and_quota`
- [x] CLI `serve-many` 转发审计和配额 -> `tests/test_cli_mcp_runtime.py::test_serve_many_forwards_audit_and_quota`
- [x] 非法配额配置退出 1 -> `tests/test_cli_mcp_runtime.py::test_bad_quota_config_exits_1`
- [x] 两个审计参数互斥 -> `tests/test_cli_mcp_runtime.py::test_audit_flags_are_exclusive`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.mcp.runtime import AuditedMcpRunner` -> 当前 `ImportError`
- [x] 反例 2：`serve --audit-file FILE` -> 当前 argparse 退出 2，不认识该参数
- [x] 反例 3：`serve --quota-config FILE` -> 当前 argparse 退出 2，不认识该参数
- [x] 反例 4：MCP 工具调用跑完后审计缓冲为空 -> 当前没有包装，确实为空
- [x] 反例 5：配额用尽时 agent 仍然运行 -> 当前没有配额检查，确实会运行

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`，再改代码。已加 `serve` / `serve-many` 的审计与配额一节。

## 5 问威胁建模（10 分钟）

1. **数据**：MCP 请求文本、token principal、审计事件、配额计数。
2. **调用方**：MCP host、控制台运维。
3. **信任边界**：host 到 MCP 进程，进程到审计服务和 Postgres。
4. **恶意输入最坏结果**：MCP 路径绕过审计或配额，让调用不留痕或突破租户上限；伪造 principal 让审计记到别人租户；审计失败静默吞掉。缓解是包装在 token principal 上、无 principal 归到 local、配额与审计都在调用前或调用后显式写、审计失败向上抛而不是吞。审计只存请求 hash，不存原文。
5. **失败是否泄露信息**：审计事件不含请求原文，只含 hash。配额拒绝只抛 `QuotaExceeded`，错误文案固定。审计服务不可用时运行失败，错误里不带审计 URL。

## 范围外

- A2A 路径的审计和配额。
- 工具调用级的事件。ADK 的工具循环仍只产生 `agent.run` 一条。
- MCP 路径的 trace 树和计划视图。
- 审批门接入 MCP。
- 匿名模式的租户配置。当前固定 `local`。

## 证据

- 反例红: `docs/evidence/SLICE-046-mcp-runtime-audit-quota.txt`，`mcp.runtime` ImportError，两个参数 argparse 退出 2，两个入口的签名里没有审计和配额
- 实现后绿: 同文件，33 passed；`check.py --fast` ALL PASS（517 passed, 9 skipped），`--full` ALL PASS
- 真实 MCP HTTP: 同文件，第一次调用返回模型回复，第二次返回工具错误，审计文件里一条 ok 带 result_hash，一条 denied quota_exceeded，拒绝的调用没有触发模型
