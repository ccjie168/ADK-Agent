# SLICE-095 A2A 出站调用审计

状态: merged
依据: ADR-0015 第 4 条。

## 意图（要什么，不写怎么写）

本地 agent 调用远端 A2A agent 时，现在的审计只记本地 run，看不到“这一跑打到了哪个 peer 的哪个 agent”。这一刀在 HTTP 出口补一条 `egress="third_party"` 事件，并把跨组织审计边界写进契约。

- 新增 `AuditTransport`，包在消费方 httpx 客户端外面，每次请求写一条 `a2a.call`。
- `remote_agent` 增加可选的 `audit`、`peer_id`、`tenant`、`subject`；不给 audit 时行为不变。
- 不读请求体与响应体，只记方法、路径哈希、状态、耗时与 trace。
- 不改变进站审计（ADR-0014 的 `peer.call` 拒绝记录）。

## 新增文件

- `src/adk_agent/a2a_egress.py`
- `tests/test_a2a_egress.py`
- `docs/evidence/SLICE-095-a2a-egress-audit.txt`
- `docs/specs/SLICE-095-a2a-egress-audit.md`

## 修改文件

- `src/adk_agent/a2a.py`（`remote_agent` 参数与客户端装配）
- `src/adk_agent/__init__.py`（如需要导出）
- `docs/contracts/a2a.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditTransport(inner: httpx.AsyncBaseTransport, *,
               audit: AuditSink,
               tenant: str, subject: str,
               peer_id: str, target: str,
               trace_id: Callable[[], str | None] | None = None)

每次请求写 AuditEvent:
  action="a2a.call"
  target="<peer_id>/<agent name>"
  tenant / principal 来自构造参数（默认 local / a2a_consumer）
  egress="third_party"
  status="ok"（响应 < 500）或 "error"（>= 500 或传输异常）
  args_hash=hash_text(f"{method} {url.path}")
  trace_id 取当前 invocation，取不到则新建
  latency_ms=实际耗时
  agent_ref=AgentRef(id=<agent name>, version="remote", digest=<card url 哈希>)

remote_agent(name, card, *, audit=None, peer_id=None,
             tenant="local", subject="a2a_consumer", ...)
  有 audit 时必须给 peer_id，否则 ValueError。
```

## 完成判据（可执行）

- [x] 成功请求写一条 ok 事件 -> `tests/test_a2a_egress.py::test_ok_event`
- [x] 5xx 写 error 事件 -> `::test_server_error_event`
- [x] 传输异常写 error 并重新抛出 -> `::test_transport_error_event`
- [x] 事件带 third_party、target 与路径哈希 -> `::test_event_shape`
- [x] trace 取自 invocation -> `::test_trace_from_invocation`
- [x] `remote_agent` 有 audit 时必须给 peer_id -> `::test_remote_agent_requires_peer`
- [x] 无 audit 时不包 transport -> `::test_remote_agent_without_audit`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.a2a_egress import AuditTransport` -> 当前 `ImportError`
- [x] 反例 2：`remote_agent(..., audit=sink, peer_id="crm")` -> 当前 `TypeError`
- [x] 反例 3：一次请求后审计里没有 `a2a.call` -> 当前确认缺失

## 契约（如涉及对外接口）

先补 `docs/contracts/a2a.md` 的出站审计段。

## 5 问威胁建模（10 分钟）

1. **数据**：请求方法、路径、状态、耗时、peer 与远端 agent 名。
2. **调用方**：控制台或服务里运行本地 agent 的进程。
3. **信任边界**：本地进程到远端 peer 的 HTTP 出口。
4. **恶意输入最坏结果**：审计里泄露请求体或响应体（缓解：只记方法、路径哈希与状态，不读 body）；trace 丢失导致无法关联（缓解：优先读当前 invocation，缺失时新建）；错误被审计吞掉（缓解：记 error 后原样抛出）；审计故障影响调用（缓解：审计失败只记录日志，不改变请求结果）。
5. **失败是否泄露信息**：事件不含完整 URL、凭据、body 或远端错误体。

## 范围外

- 远端 agent 的加载与对话入口。
- 目录刷新时的 card 拉取审计（已有 `remote_agent.refresh`）。
- 跨组织端到端可验证审计。
- 出站限流与配额。

## 证据

- 反例红：`docs/evidence/SLICE-095-a2a-egress-audit.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，回环服务器、真实 httpx 与 JSONL 审计
