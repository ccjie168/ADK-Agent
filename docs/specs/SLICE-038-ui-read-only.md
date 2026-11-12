# SLICE-038 只读运营视图（UI-1）

状态: gated
依据: ADR-0002 第 2、6 条。参考 Google ADK Web 与 Vertex AI Agent Engine 控制台。

## 意图（要什么，不写怎么写）

在现有控制台上补一个只读运营面，让运维能看见注册表、运行历史和会话，不只看当前进程的聊天。

参考来源分两块。Agent Engine 控制台给管理面的骨架，agent 列表、详情、会话、事件。ADK Web 给调试深度，session 切换、event 历史、trace、Eval 结果。这一刀只做只读，不抄 Visual Builder，也不做指标页。

四块数据：

- 注册表。已发布的 agent，按租户列出，含 id、版本、摘要、发布时间、digest、是否有评测报告。
- 评测报告。发布时带 `--eval-report` 的报告要留存，UI 才能按版本查看。
- 运行历史。从控制台进程的审计缓冲按 `run_id` 聚合，给出开始时间、结束时间、状态、延迟、成本、事件数。点击可看现有 trace。
- 会话。按 agent 列出会话 id 和最后更新时间，不返回 state 和 events。

前端仍是服务端静态页加原生 JS，不引入构建链。页面分 Chat、Registry、Runs、Sessions、Policy 五个标签，现有的进度、trace、审计面板保留。

这一刀不做审批、指标、state 编辑、租户与角色管理、分页和 SPA。

## 新增文件

- `src/adk_agent/registry/reports.py`
- `tests/registry/test_eval_reports.py`
- `tests/test_console_registry.py`
- `tests/test_console_runs.py`
- `tests/test_console_sessions.py`
- `docs/evidence/SLICE-038-ui-read-only.txt`

## 修改文件

- `src/adk_agent/core/ports.py`：`AgentRegistry` 增加 `list(tenant)` 和 `tenants()`，新增 `EvalReportStore` 端口
- `src/adk_agent/core/__init__.py`：导出新端口。`EvalReportConflict` 留在 `registry/reports.py`，避免 core 依赖适配器
- `src/adk_agent/registry/file.py`：实现 `list` 和 `tenants`，非法租户抛 `ValueError`
- `src/adk_agent/registry/__init__.py`：导出 `FileEvalReportStore` 和 `EvalReportConflict`
- `src/adk_agent/cli.py`：`console` 增加 `--registry`，`publish` 留存评测报告
- `src/adk_agent/console.py`：注册表、run、会话接口与新面板
- `docs/contracts/console.md`：先写四个新接口和错误码
- `docs/contracts/cli.md`：`console --registry` 与 `publish` 留存报告
- `tests/test_layering.py`：端口方法清单加上新方法
- `docs/specs/ROADMAP.md`：登记 SLICE-038

## 数据形状

注册表条目是 `PublishedAgent` 的派生视图，不新增持久 schema。

```text
RegistryEntry = {
  tenant: str, id: str, version: str, digest: str,
  description: str, published_at: ISO8601,
  has_eval_report: bool, manifest: object
}
RunSummary = {
  run_id: str, trace_id: str, agent_id: str, tenant: str,
  status: "ok" | "error" | "denied", started_at: ISO8601,
  last_at: ISO8601, latency_ms: int | null, cost_usd: float | null,
  events: int
}
SessionSummary = { session_id: str, last_update_time: ISO8601 }
```

评测报告沿用现有 `EvalReport`。存放路径是 `<registry>/<tenant>/<id>/<version>.eval.json`，和版本文件同级，原子写入。

## 完成判据（可执行）

- [x] 注册表列出已发布记录，按 `(id, version)` 排序 -> `tests/registry/test_file_registry.py::test_list_returns_published_records`
- [x] 注册表列出租户，按字典序，根目录不存在时为空 -> `tests/registry/test_file_registry.py::test_tenants_sorted_and_missing_root`
- [x] 非法租户被拒绝 -> `tests/registry/test_file_registry.py::test_list_rejects_unsafe_tenant`
- [x] 损坏记录让列表失败，不静默跳过 -> `tests/registry/test_file_registry.py::test_list_surfaces_corrupt_record`
- [x] 非法 JSON 记录抛 `RegistryIntegrityError` -> `tests/registry/test_file_registry.py::test_list_surfaces_malformed_record`
- [x] 评测报告可写入并按版本读回 -> `tests/registry/test_eval_reports.py::test_put_then_get_report`
- [x] 同版本相同报告幂等 -> `tests/registry/test_eval_reports.py::test_put_same_report_is_idempotent`
- [x] 同版本不同报告冲突 -> `tests/registry/test_eval_reports.py::test_put_different_report_conflicts`
- [x] `publish --eval-report` 落盘报告 -> `tests/test_eval_gate.py::test_publish_persists_eval_report`
- [x] 重新发布可补写报告 -> `tests/test_eval_gate.py::test_republish_finishes_missing_report`
- [x] `GET /api/tenants` 返回排序后的租户 -> `tests/test_console_registry.py::test_tenants_endpoint`
- [x] `GET /api/registry?tenant=` 返回条目和评测标记 -> `tests/test_console_registry.py::test_registry_listing`
- [x] `GET /api/registry/{tenant}/{id}/{version}/eval` 返回报告 -> `tests/test_console_registry.py::test_eval_report_endpoint`
- [x] 未配置注册表时返回 404 `registry_not_configured` -> `tests/test_console_registry.py::test_registry_not_configured`
- [x] 非法 JSON 记录返回 500 `registry_corrupt` 且不含路径 -> `tests/test_console_registry.py::test_malformed_record_is_500_without_path`
- [x] `GET /api/runs` 按 `run_id` 聚合并按最后事件倒序 -> `tests/test_console_runs.py::test_runs_group_by_run_id`
- [x] `GET /api/runs?limit=` 夹在 1 到 200 -> `tests/test_console_runs.py::test_runs_limit_is_clamped`
- [x] `GET /api/sessions?agent=` 只返回 id 和最后更新时间 -> `tests/test_console_sessions.py::test_sessions_omit_state_and_events`
- [x] 未知 agent 返回 400 `unknown_agent` -> `tests/test_console_sessions.py::test_sessions_reject_unknown_agent`
- [x] 首页含五个标签和三个新面板 -> `tests/test_console.py::test_index_has_management_panels`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry.reports import FileEvalReportStore` -> 当前 `ImportError`
- [x] 反例 2：`GET /api/tenants` -> 当前 404
- [x] 反例 3：`GET /api/registry?tenant=../x` -> 期望 400 `unsafe_tenant`，不拼路径
- [x] 反例 4：注册表里放一个 digest 不匹配或语法损坏的 JSON -> 期望 500 `registry_corrupt`，响应不含文件路径
- [x] 反例 5：`publish --eval-report` 后报告文件不存在 -> 当前确实不存在，期望存在
- [x] 反例 6：`adk-agent console --registry DIR` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 和 `docs/contracts/cli.md`，再改代码。

- `GET /api/tenants` -> `[str]`
- `GET /api/registry?tenant=<name>` -> `[RegistryEntry]`，非法租户 400 `unsafe_tenant`，记录损坏 500 `registry_corrupt`
- `GET /api/registry/{tenant}/{id}/{version}/eval` -> `EvalReport`，没有报告 404 `eval_report_not_found`
- `GET /api/runs?limit=50` -> `[RunSummary]`，`limit` 夹在 1 到 200
- `GET /api/sessions?agent=<name>` -> `[SessionSummary]`，未知 agent 400 `unknown_agent`
- `console --registry DIR`，默认 `$ADK_REGISTRY_DIR`，否则 `./registry`
- `publish` 成功写入版本后，把评测报告写到同目录的 `<version>.eval.json`，重复发布可补写

## 5 问威胁建模（10 分钟）

1. **数据**：manifest 里的指令、模型策略和工具授权，评测报告的用例输入与期望输出，会话 id，运行元数据。
2. **调用方**：持有控制台 bearer token 的运维。
3. **信任边界**：浏览器到控制台的 HTTP，控制台到注册表文件，控制台到会话存储。
4. **恶意输入最坏结果**：tenant、id、version 来自 URL。不校验就能路径穿越，读写注册表目录之外的文件。缓解是每个路径分量都过 `_SAFE_NAME`，只走 `_path`。损坏记录会让列表 500，但不返回路径和堆栈。评测用例可能含业务数据，所以报告接口必须鉴权。
5. **失败是否泄露信息**：错误只返回固定代码。`registry_corrupt` 不写文件名，`unsafe_tenant` 不回显输入。

## 范围外

- 审批收件箱和计划可视化，排在 OIDC 之后。
- 指标页，排在指标与追踪切片之后。
- state 查看与编辑，需要 OIDC 给真实主体。
- 会话按用户隔离。UI-1 只有单一本地用户。
- 跨进程运行历史。UI-1 的 run 列表来自控制台进程内的审计缓冲，多副本下各看各的。
- 分页、排序选项、SPA 构建链。

## 证据

- 反例红: `docs/evidence/SLICE-038-ui-read-only.txt`，`adk_agent.registry.reports` 和 `_summarize_runs` 不存在，4 个测试文件收集失败
- 实现后绿: 同文件，47 个目标测试通过，全量 392 passed 2 skipped，`check.py --full` ALL PASS，另做真实浏览器验证
