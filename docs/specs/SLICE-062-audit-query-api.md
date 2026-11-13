# SLICE-062 审计只读查询 API

状态: planned
依据: SLICE-035，SLICE-053，`docs/contracts/cli.md`，`docs/reviews/architecture-direction-20261113.md` 的 Phase A。

## 意图（要什么，不写怎么写）

审计服务只有写路径。控制台的审计与运行面板读的是本进程缓冲，多副本时换一个副本就是空的。这一刀给审计服务加只读查询，作为"集中可见性"的第一步。

- `AuditPipeline` 所在模块提供 `query_events(path, ...)`，读全部段文件并按条件过滤。
- 审计服务新增 `GET /v1/events`，见 `docs/contracts/cli.md`。
- 过滤条件：tenant、trace_id、run_id、action、status、since、until；排序 desc/asc；limit 1 到 1000。
- OIDC 模式下缺省租户取 token，非 admin 不能查其他租户；静态 token 和免鉴权模式不限制。
- 读取当前段时忽略末尾半行，其余解析失败返回 502。

这一刀不改控制台，控制台接线是下一刀。

## 新增文件

- `tests/audit/test_query.py`
- `docs/evidence/SLICE-062-audit-query-api.txt`

## 修改文件

- `src/adk_agent/audit/pipeline.py`：`query_events`
- `src/adk_agent/audit/service.py`：`GET /v1/events`
- `src/adk_agent/audit/__init__.py`：导出
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
query_events(path, *, tenant=None, trace_id=None, run_id=None, action=None,
             status=None, since=None, until=None, limit=100, order="desc")
  -> list[AuditEvent]        # 按 timestamp，其次写入顺序；order=desc 反转
  # 只读取 .NNNNNN 段和当前文件；当前文件末尾半行忽略

GET /v1/events -> 200 {"events": [AuditEvent], "count": int}
  400 invalid_status | invalid_time | invalid_limit | invalid_order
  403 tenant_forbidden
  502 audit_read_failed
```

## 完成判据（可执行）

- [ ] 按租户过滤且默认最新在前 -> `tests/audit/test_query.py::test_filters_by_tenant`
- [ ] `order=asc` 反转 -> `tests/audit/test_query.py::test_order_asc`
- [ ] limit 生效 -> `tests/audit/test_query.py::test_limit`
- [ ] trace、run、action、status 过滤 -> `tests/audit/test_query.py::test_field_filters`
- [ ] 时间区间过滤 -> `tests/audit/test_query.py::test_time_range`
- [ ] 末尾半行被忽略 -> `tests/audit/test_query.py::test_trailing_partial_line_ignored`
- [ ] 分段的记录都能查到 -> `tests/audit/test_query.py::test_reads_segments`
- [ ] HTTP 查询返回事件与数量 -> `tests/audit/test_query.py::test_http_query`
- [ ] 非法参数返回 400 -> `tests/audit/test_query.py::test_http_rejects_bad_params`
- [ ] OIDC 非 admin 跨租户 403 -> `tests/audit/test_query.py::test_oidc_tenant_forbidden`
- [ ] OIDC 缺省租户取 token -> `tests/audit/test_query.py::test_oidc_defaults_to_token_tenant`
- [ ] OIDC admin 可跨租户 -> `tests/audit/test_query.py::test_oidc_admin_cross_tenant`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.audit import query_events` -> 当前 `ImportError`
- [ ] 反例 2：`GET /v1/events` -> 当前 405 / 404（路由不存在）
- [ ] 反例 3：`limit=0` 若直接返回全部记录而不是 400 -> 由 `test_http_rejects_bad_params` 覆盖

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md` 的 `GET /v1/events` 一节。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件，含主体、目标、哈希、时间；可能含敏感上下文的哈希而非明文。
2. **调用方**：控制台、运维、未来的治理视图。
3. **信任边界**：审计服务到存储文件；token 租户到查询结果。
4. **恶意输入最坏结果**：跨租户读取审计（缓解：OIDC 按 token 绑定，非 admin 越权 403）；超大 limit 拖垮内存（上限 1000）；非法时间导致解析异常（400）；读取半行导致 500（忽略末尾半行）。
5. **失败是否泄露信息**：403 与 400 只给固定错误码；502 不返回文件内容。

## 范围外

- 全文搜索、分页游标、按哈希或主体过滤。
- 控制台接线（下一刀）。
- 审计后端的换库；仍是 JSONL 文件。
- 读取时校验哈希链；查询只读事件，校验仍用 `verify-audit`。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
