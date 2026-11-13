# SLICE-063 控制台接共享审计

状态: planned
依据: SLICE-038，SLICE-062，`docs/contracts/console.md`，`docs/contracts/cli.md`。

## 意图（要什么，不写怎么写）

控制台的审计、运行和 trace 面板读的是本进程缓冲。多副本运行时每个副本只看到自己的历史。上一刀给了审计服务只读查询，这一刀把控制台的读写都接到同一份审计数据上。

- 新增 `AuditQuery` 协议、`HttpAuditQuery`（查审计服务）和 `FileAuditQuery`（查本地 JSONL）。
- 控制台 CLI 增加 `--audit-file`、`--audit-url`、`--audit-token-env`。写路径用现成的 `JsonlAuditSink` / `HttpAuditSink`，读路径用对应的 query。
- 都不给时行为不变，读进程内缓冲。
- `/api/audit`、`/api/runs`、`/api/traces` 在配置了 query 时从它读。非 admin 只查自己租户，admin 查全部。
- 审计服务不可用返回 502 `audit_unavailable`。
- 非回环 `--audit-url` 没有 token 拒绝启动，沿用其他服务的规则。

## 新增文件

- `src/adk_agent/audit/query.py`
- `tests/test_console_shared_audit.py`
- `docs/evidence/SLICE-063-console-shared-audit.txt`

## 修改文件

- `src/adk_agent/audit/http_sink.py`：`HttpAuditQuery`、`AuditQueryUnavailable`
- `src/adk_agent/audit/__init__.py`：导出
- `src/adk_agent/console.py`：`audit_query`、读取帮助函数、异常处理器
- `src/adk_agent/cli.py`：控制台的审计参数与 query 装配
- `docs/contracts/cli.md`、`docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditQuery (Protocol)
  async events(*, tenant: str | None, limit: int) -> list[AuditEvent]

FileAuditQuery(path)                 # 调 query_events(order="desc")
HttpAuditQuery(base_url, auth_token) # GET /v1/events?tenant&limit=1000&order=desc
AuditQueryUnavailable                # 非 200 或连接失败

build_console_app(..., audit_query: AuditQuery | None = None)
  audit_query 为空 -> audit.recent(limit)
  非 admin -> events(tenant=principal.tenant)
  admin    -> events(tenant=None)
```

## 完成判据（可执行）

- [ ] 文件查询按租户和 limit 过滤 -> `tests/test_console_shared_audit.py::test_file_query`
- [ ] HTTP 查询传参并解析事件 -> `tests/test_console_shared_audit.py::test_http_query`
- [ ] HTTP 非 200 抛 `AuditQueryUnavailable` -> `tests/test_console_shared_audit.py::test_http_query_failure`
- [ ] `/api/audit` 从注入的 query 读 -> `tests/test_console_shared_audit.py::test_console_reads_from_query`
- [ ] 非 admin 只查本租户 -> `tests/test_console_shared_audit.py::test_console_scopes_tenant`
- [ ] admin 查询不带租户 -> `tests/test_console_shared_audit.py::test_console_admin_query`
- [ ] query 失败返回 502 -> `tests/test_console_shared_audit.py::test_console_maps_outage`
- [ ] CLI `--audit-url` 装配读写两端 -> `tests/test_console_shared_audit.py::test_cli_wires_audit_url`
- [ ] CLI `--audit-file` 装配文件读写 -> `tests/test_console_shared_audit.py::test_cli_wires_audit_file`
- [ ] 非回环无 token 退出 1 -> `tests/test_console_shared_audit.py::test_cli_requires_token`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.audit import HttpAuditQuery` -> 当前 `ImportError`
- [ ] 反例 2：`console --audit-url ...` -> 当前 argparse 退出 2（参数不存在）
- [ ] 反例 3：注入 query 后服务失败若返回空列表而不是 502 -> 由 `test_console_maps_outage` 覆盖

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md`（console 审计参数）与 `docs/contracts/console.md`（三个读接口）。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件，可能包含只属于某租户的运行细节；审计 token。
2. **调用方**：控制台进程和浏览器。
3. **信任边界**：控制台到审计服务；浏览器到控制台。
4. **恶意输入最坏结果**：非 admin 借控制台读别租户事件（缓解：按 principal 传 tenant，服务端再校验一次）；审计 token 泄露到命令行（只从环境变量读，非回环无 token 拒绝启动）；审计服务故障导致控制台 500（映射为 502 固定文案）。
5. **失败是否泄露信息**：502 只回 `audit_unavailable`，不回内部 URL 或异常文本。

## 范围外

- 审计服务故障时的离线缓存或降级读取。
- 分页与无限滚动。
- 控制台写入审计的离线队列。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
