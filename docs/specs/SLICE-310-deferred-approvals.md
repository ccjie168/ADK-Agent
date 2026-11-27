# SLICE-310 延迟审批（ADR-0049 切片 1）

状态: active
依据: ADR-0049 已确认（2026-11-27），按用户同意的顺序先做异步审批

## 意图

让需要审批的计划步骤不再阻塞调用方：返回 `PlanPending` 与 request id，等决策后
用同一 `run_id` 恢复。本期只做库层（`PlanExecutor` 与检查点），不改服务与协议。

## 契约（先改）

`docs/decisions/ADR-0049-deferred-approvals.md` 已定；本切片对外只新增两个类型：

- `core.PlanPending`（`plan_id`、`version`、`run_id`、`trace_id`、`request_id`、
  `step_id`、`expires_at`）；
- `orchestration.ApprovalDeferred`（内部信号，不穿透到调用方）。

`PlanExecutor(defer_approvals=True)`：延迟模式下 request id 由
`(tenant, run_id, step_id)` 的 uuid5 决定，未给超时则用 `defer_ttl_seconds`
（默认 3600）保证 `expires_at` 非空。

## 完成判据

- [ ] 延迟运行返回 `PlanPending` 并生成审批请求 -> `test_deferred_run_returns_pending_and_creates_request`
- [ ] 批准后恢复，只补跑剩余步骤 -> `test_approved_resume_runs_the_remaining_step`
- [ ] 拒绝后抛 `ApprovalDenied` 且不执行该步 -> `test_denied_resume_raises_and_skips_the_step`
- [ ] 未决时重复进入仍是同一请求 -> `test_pending_reentry_is_stable`
- [ ] 同步模式行为不变 -> `test_sync_mode_still_waits`
- [ ] 不能提交的审批端口报协议错误 -> `test_defer_requires_a_submit_capable_gate`
- [ ] 默认 TTL 保证有到期时间 -> `test_pending_expires_from_the_defer_ttl`
- [ ] `--full` 门禁通过

## 反例

实现前 `PlanExecutor` 没有 `defer_approvals` 参数，`PlanPending` 与
`ApprovalDeferred` 不存在，以上 7 条用例全部失败（`TypeError`/`ImportError`）。

## 5 问威胁建模

1. **数据**：审批请求含步骤输入；检查点含各步输出。
2. **调用方**：库层，无网络面；延迟模式由服务在 0049-2/3 决定是否开启。
3. **信任边界**：恢复前校验 `plan_digest`；request id 确定性但不可猜（uuid5 含 run/step）。
4. **恶意输入**：恢复时若计划被替换，digest 不一致直接 `CheckpointCorrupt`。
5. **失败是否泄露信息**：错误只带步骤 id 与 request id。

## 范围外

- 服务端开关、resumer、通知、控制台状态（0049-2）。
- A2A `input-required`、MCP 状态工具（0049-3）。
- 审计 `status` 词表新增 `waiting`。

## 证据

- `docs/evidence/SLICE-310-deferred-approvals.txt`
