# SLICE-048 A2A 路径接入审计与配额

状态: spec'd
依据: SLICE-031，SLICE-046，SLICE-047，`docs/contracts/cli.md`，`docs/contracts/tracing.md`

## 意图（要什么，不写怎么写）

A2A 的 `serve-a2a` 现在直接把 agent 交给 ADK 的 `to_a2a`，不经过 `AgentRuntime`，所以没有 `agent.run` 审计，也不受租户配额约束。这一刀把 SLICE-046 的运行包装复用到 A2A 上。

- 把 MCP 的 `AuditedMcpRunner` 提升成通用的 `AuditedRunner`，放到 `runtime/audit_proxy.py`。`mcp/runtime.py` 保留同名导出，MCP 行为不变。
- 包装器支持两种输入文本来源：显式字符串（MCP 的 request）和从 `new_message` 的文本 part 推导（A2A）。`args_hash` 用推导出的文本。
- 包装器支持 `trace_id` 是字符串或返回字符串的 callable。A2A 用请求作用域的 callable，从 `traceparent` 取。
- `serve-a2a` 和 `build_a2a_app` 接受 `audit`、`quota`、`quota_config`。tenant 固定 `local`，principal 是 `a2a_user`（kind service）。
- 没有传 runner 且启用了审计或配额时，用 ADK 的默认 runner 包装。
- A2A app 外层加一个纯 ASGI 中间件，把 `traceparent` 解析成 trace id 放进 ContextVar，供包装器读取。
- CLI 加 `--audit-file`、`--audit-url`、`--audit-token-env`、`--quota-config`，复用现有 helper。

这一刀不做 A2A 的指标端点、A2A 消费方（`RemoteA2aAgent`）的审计，也不做 A2A 的审批门。

## 新增文件

- `src/adk_agent/runtime/audit_proxy.py`：`AuditedRunner`、`wrap_runner`
- `tests/test_a2a_runtime.py`
- `tests/test_cli_a2a_runtime.py`
- `docs/evidence/SLICE-048-a2a-audit-quota.txt`

## 修改文件

- `src/adk_agent/mcp/runtime.py`：改为从 `runtime.audit_proxy` 重新导出 `AuditedMcpRunner`
- `src/adk_agent/mcp/server.py`：导入路径不变，确认行为不变
- `src/adk_agent/a2a.py`：`build_a2a_app` / `serve_a2a` 的审计、配额、trace 中间件
- `src/adk_agent/cli.py`：`serve-a2a` 的四个参数
- `docs/contracts/cli.md`、`docs/contracts/tracing.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditedRunner:
  inner, agent_name, principal, input_text: str | None,
  audit, quota, quota_policy, trace_id: str | Callable[[], str | None] | None
  run_async(**kwargs):
    - input = input_text if 非 None else 从 kwargs["new_message"] 的文本 part 拼接
    - trace = trace_id() if callable else trace_id or uuid4().hex
    - 配额、审计、异常语义与 SLICE-046 相同

A2A:
  tenant = "local"
  principal = Principal(tenant="local", subject="a2a_user", kind="service")
  quota_policy = quota_config.tenants.get("local")
  trace_id = lambda: _trace_id_var.get()
```

纯 ASGI 中间件：

```text
_TraceContextMiddleware(app):
  scope["type"] == "http" -> token = var.set(resolve_trace_id(None, headers.get("traceparent")))
  finally var.reset(token)
```

## 完成判据（可执行）

- [ ] A2A 调用写 ok 审计 -> `tests/test_a2a_runtime.py::test_a2a_audits_run`
- [ ] 审计带消息文本哈希和回复哈希 -> `tests/test_a2a_runtime.py::test_a2a_audits_run`
- [ ] 配额用尽写 denied 且不调用模型 -> `tests/test_a2a_runtime.py::test_a2a_quota_denies`
- [ ] 审计 trace_id 取 traceparent -> `tests/test_a2a_runtime.py::test_a2a_uses_traceparent`
- [ ] 没有 traceparent 时生成 32 位十六进制 -> `tests/test_a2a_runtime.py::test_a2a_generates_trace_id`
- [ ] MCP 包装器行为不变 -> `tests/test_mcp_runtime.py` 全部通过
- [ ] MCP 接线行为不变 -> `tests/test_mcp_runtime_wiring.py` 全部通过
- [ ] CLI `serve-a2a` 转发审计和配额 -> `tests/test_cli_a2a_runtime.py::test_serve_a2a_forwards_audit_and_quota`
- [ ] 非法配额配置退出 1 -> `tests/test_cli_a2a_runtime.py::test_bad_quota_config_exits_1`
- [ ] 默认关闭 -> `tests/test_cli_a2a_runtime.py::test_runtime_flags_default_off`
- [ ] 两个审计参数互斥 -> `tests/test_cli_a2a_runtime.py::test_audit_flags_are_exclusive`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.runtime.audit_proxy import AuditedRunner` -> 当前 `ImportError`
- [ ] 反例 2：`build_a2a_app(agent, audit=sink)` -> 当前 `TypeError`，不认识 `audit`
- [ ] 反例 3：A2A `message/send` 跑完后审计缓冲为空 -> 当前确实为空
- [ ] 反例 4：配额用尽时 A2A 仍然运行 agent -> 当前没有配额检查
- [ ] 反例 5：`serve-a2a --audit-file FILE` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。已改：

- `cli.md`：`serve-a2a` 的四个参数和审计语义。
- `tracing.md`：A2A 也读取 `traceparent`。

## 5 问威胁建模（10 分钟）

1. **数据**：A2A 消息文本、final 回复、审计事件、配额计数、trace id。
2. **调用方**：A2A 客户端、其他 agent。
3. **信任边界**：客户端到 A2A HTTP，进程到审计服务和 Postgres。
4. **恶意输入最坏结果**：A2A 路径绕过审计或配额；伪造 trace 头把别人的 trace 串起来；消息原文进审计。缓解是包装在 A2A runner 上、身份固定为 local/a2a_user、审计只存 hash、trace 头只做格式校验和长度限制。
5. **失败是否泄露信息**：审计失败按现有语义向上抛，错误里不带审计 URL。配额拒绝只抛 `QuotaExceeded`。审计不含消息原文。

## 范围外

- A2A 的指标端点。
- `RemoteA2aAgent` 消费方的审计。它在本进程外。
- A2A 的审批门和工具守卫。
- A2A 的多租户身份。A2A 目前只有 bearer token，没有 OIDC principal。

## 证据

- 反例红: 待补
- 实现后绿: 待补
