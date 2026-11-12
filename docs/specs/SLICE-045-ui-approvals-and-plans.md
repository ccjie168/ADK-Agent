# SLICE-045 控制台审批收件箱与计划可视化（UI-2）

状态: gated
依据: SLICE-027，SLICE-036，SLICE-038，`docs/contracts/console.md`，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

把 SLICE-027 的审批门做成控制台里可用的收件箱，并把编排计划的历史和 trace 放进控制台。

- 新增 `FileApprovalInbox`，实现 `ApprovalGate` 端口，用目录里的两个文件保存一条审批：待决请求和不可改写的决定。
- 审批请求和决定跨进程可见。执行器和控制台可以是两个进程，执行器等待决定文件出现。
- 决定用独占创建写入，第二次决定抛冲突。决定不可改写。
- 控制台加 `--approval-dir`，默认 `$ADK_APPROVAL_DIR`。不设置时审批接口禁用，返回 404。
- `GET /api/approvals` 列出待决请求，按请求时间正序。非 admin 只能看自己租户。
- `POST /api/approvals/{request_id}` 记录通过或拒绝。审批人取当前 principal 的 subject。每次成功决定写一条 `approval.decide` 审计，不含待审输入。
- 配置 `--policy` 时按 `approval.decide:<agent_id>` 判 RBAC，默认拒绝。
- `GET /api/plans` 从审计缓冲聚合 `orchestration.run`，给出步骤数、审批数、状态和耗时。控制台加 Plans 面板，点击看计划 trace。
- 控制台加 Approvals 面板，能看请求详情并批准或拒绝。

这一刀不做审批的推送通知、审批超时后的自动清理、多级审批，也不做计划重放。

## 新增文件

- `src/adk_agent/approvals.py`：`FileApprovalInbox`、`ApprovalRecord`、`ApprovalConflict`、`ApprovalNotFound`、`InvalidApprovalRequest`
- `tests/test_approvals.py`
- `tests/test_console_approvals.py`
- `tests/test_console_plans.py`
- `docs/contracts/approval_request.schema.json`
- `docs/contracts/approval_decision.schema.json`
- `docs/evidence/SLICE-045-ui-approvals-and-plans.txt`

## 修改文件

- `src/adk_agent/console.py`：`build_console_app(approvals=)`、`run_console(approvals=)`、三个接口、两个面板、`_summarize_plans`
- `src/adk_agent/cli.py`：`console --approval-dir`
- `scripts/export_contracts.py`：导出审批两个类型
- `docs/contracts/README.md`、`docs/contracts/cli.md`、`docs/contracts/console.md`
- `tests/test_console.py`：索引断言加上新面板
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
FileApprovalInbox(root: Path, *, poll_seconds=0.5, clock=utcnow):
  submit(request: ApprovalRequest) -> None
  request(request: ApprovalRequest) -> ApprovalDecision    # ApprovalGate 端口，轮询直到决定出现
  decide(request_id, *, approved: bool, approver: str, reason="") -> ApprovalDecision
  pending() -> list[ApprovalRequest]
  get(request_id) -> ApprovalRecord | None

ApprovalRecord:
  request: ApprovalRequest
  decision: ApprovalDecision | None
```

目录布局：

```text
<root>/<request_id>.request.json     # ApprovalRequest，一次性写入，同 id 同内容幂等
<root>/<request_id>.decision.json    # ApprovalDecision，独占创建，已存在即冲突
```

- 请求 id 必须匹配 `^[A-Za-z0-9._-]{1,128}$`，否则 `InvalidApprovalRequest`。文件名只由校验过的 id 构成。
- 请求文件先写临时文件再 `os.replace`。同 id 不同内容抛 `ApprovalConflict`。
- 决定先写临时文件再 `os.link` 到目标名。`os.link` 在目标存在时失败，第二次决定抛 `ApprovalConflict`。
- `pending()` 读所有请求文件，跳过已有决定文件和文件名非法的项，按 `requested_at` 正序。
- `request()` 先 `submit`，再以 `poll_seconds` 间隔读决定文件。`CancelledError` 直接向上抛，待决文件保留。
- 决定不可改写，文件也没有删除路径。清理是范围外。

计划摘要：

```text
PlanSummary:
  trace_id, plan_id(event.target), agent_id(agent_ref.id), tenant,
  status, error_code, started_at, last_at,
  steps(同 trace 的 orchestration.step 数),
  approvals(同 trace 的 orchestration.approval 数),
  latency_ms, cost_usd
```

## 完成判据（可执行）

- [x] 提交后出现在待决列表 -> `tests/test_approvals.py::test_submit_then_pending`
- [x] 决定后不再待决 -> `tests/test_approvals.py::test_decide_removes_from_pending`
- [x] 第二次决定冲突且不改写 -> `tests/test_approvals.py::test_second_decision_conflicts`
- [x] 未知请求 -> `tests/test_approvals.py::test_unknown_request_not_found`
- [x] 非法 id 被拒 -> `tests/test_approvals.py::test_unsafe_request_id_rejected`
- [x] 同 id 同内容幂等 -> `tests/test_approvals.py::test_same_request_is_idempotent`
- [x] 同 id 不同内容冲突 -> `tests/test_approvals.py::test_conflicting_resubmit_rejected`
- [x] 门等待另一实例的决定 -> `tests/test_approvals.py::test_gate_waits_for_decision`
- [x] 取消后请求保留 -> `tests/test_approvals.py::test_gate_cancellation_leaves_pending`
- [x] 两个收件箱共享决定 -> `tests/test_approvals.py::test_two_inboxes_share_decisions`
- [x] 未配置审批目录返回 404 -> `tests/test_console_approvals.py::test_approvals_not_configured`
- [x] 非 admin 只看到自己租户 -> `tests/test_console_approvals.py::test_list_pending_filters_by_tenant`
- [x] admin 看到所有租户 -> `tests/test_console_approvals.py::test_admin_sees_all_tenants`
- [x] 决定记录审批人和审计 -> `tests/test_console_approvals.py::test_decide_records_approver_and_audit`
- [x] 审计不含待审输入 -> `tests/test_console_approvals.py::test_audit_has_no_input`
- [x] 跨租户决定被拒 -> `tests/test_console_approvals.py::test_decide_other_tenant_forbidden`
- [x] 重复决定返回 409 -> `tests/test_console_approvals.py::test_decide_twice_conflicts`
- [x] 未知请求返回 404 -> `tests/test_console_approvals.py::test_decide_unknown`
- [x] 非法 id 返回 400 -> `tests/test_console_approvals.py::test_unsafe_request_id`
- [x] 策略拒绝返回 403 -> `tests/test_console_approvals.py::test_policy_denies_decision`
- [x] 计划按 trace 聚合 -> `tests/test_console_plans.py::test_plans_group_by_trace`
- [x] 计划按租户过滤 -> `tests/test_console_plans.py::test_plans_filter_by_tenant`
- [x] 计划 limit 夹紧 -> `tests/test_console_plans.py::test_plans_limit_clamped`
- [x] 索引含新面板 -> `tests/test_console.py::test_index_has_management_panels`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.approvals import FileApprovalInbox` -> 当前 `ImportError`
- [x] 反例 2：`console --approval-dir DIR` -> 当前 argparse 退出 2，不认识该参数
- [x] 反例 3：配置审批目录后 `GET /api/approvals` -> 当前路由不存在，返回 FastAPI 的 404 `{"detail":"Not Found"}`
- [x] 反例 4：`GET /api/plans` -> 当前路由不存在
- [x] 反例 5：同一目录两个实例，一个提交一个决定 -> 当前没有实现
- [x] 反例 6：对同一请求决定两次 -> 当前没有实现；实现后第二次必须是 409，不能静默覆盖

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。已改：

- `approval_request.schema.json`、`approval_decision.schema.json`。
- `cli.md`：`console --approval-dir DIR`、`$ADK_APPROVAL_DIR`。
- `console.md`：`GET /api/approvals`、`POST /api/approvals/{request_id}`、`GET /api/plans`。

## 5 问威胁建模（10 分钟）

1. **数据**：待审的步骤输入、审批人、决定、计划摘要、审计。
2. **调用方**：计划执行器、控制台用户、运维。
3. **信任边界**：执行器到收件箱目录，控制台 HTTP 到收件箱，审计事件。
4. **恶意输入最坏结果**：未审批就执行；审批人伪造；跨租户审批；请求 id 路径穿越；待审输入泄露到审计或日志。缓解是文件名的严格 id 校验、目录内相对路径、O_EXCL/link 保证决定不可改写、租户检查和 RBAC 默认拒绝、审计只记 request id 和审批人。
5. **失败是否泄露信息**：404 不区分请求不存在和路径不合法（非法 id 单独 400 是固定文案），403 不透露请求内容，审计不含 input。目录读写失败按 500 固定文案返回，不回路径。

## 范围外

- 审批推送、邮件和通知。
- 待决请求的过期清理和归档。
- 多级审批、会签。
- 计划重放和从断点恢复。
- 审批人身份的额外校验，超出 OIDC principal 的 subject。
- 收件箱目录的权限管理。

## 证据

- 反例红: `docs/evidence/SLICE-045-ui-approvals-and-plans.txt`，审批模块 ImportError，`--approval-dir` 退出 2，两个新路由 404 `detail: Not Found`
- 实现后绿: 同文件，36 passed；`check.py --fast` ALL PASS（501 passed, 9 skipped）
- 真实跨进程: 同文件，执行器进程等待，控制台批准后步骤执行一次，决定第二次返回 409
- 真实浏览器: 同文件，Edge headless + CDP 打开 Approvals 面板，看到请求详情并点击 Approve，列表清空，Plans 面板可切换
