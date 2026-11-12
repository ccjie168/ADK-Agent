# SLICE-049 审批过期与提交提醒

状态: spec'd
依据: SLICE-027，SLICE-045，`docs/contracts/console.md`，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

待决审批目前在文件里永久保留，执行器超时放弃后，人还能看到并决定一个已经没有意义的请求。这一刀给审批加截止时间和提交提醒。

- `ApprovalRequest` 加可选 `expires_at`，必须带时区。计划执行器在审批等待有时间上限时填入，值是 `requested_at + 父 deadline 的剩余秒数`。
- `FileApprovalInbox` 的过期判定：先用请求自带的 `expires_at`，没有时用构造时的 `ttl_seconds` 兜底，两者都没有就不过期。
- `pending()` 不返回过期请求。`decide()` 对已过期且未决的请求抛 `ApprovalExpired`。`request()` 在轮询中一旦过期就抛 `ApprovalExpired`，不再无限等待。
- 已决请求即使超过截止时间仍是 409 冲突，决定不可改写。
- `FileApprovalInbox` 加 `on_submit` 回调。`request()` 提交成功后调用一次，异常只记日志，不阻止等待。回调可以是同步或异步。
- 控制台 `POST /api/approvals/{id}` 把 `ApprovalExpired` 映射成 410 `approval_expired`。`GET /api/approvals` 自然带上 `expires_at`。
- 控制台 `--approval-ttl SECONDS` 作为没有 `expires_at` 的请求的兜底。

这一刀不做文件删除和归档、不做推送渠道（邮件、Slack）、不做多级审批。

## 新增文件

- `tests/test_approvals_expiry.py`
- `tests/test_console_approvals_expiry.py`
- `tests/test_cli_approval_ttl.py`
- `tests/orchestration/test_approval_expiry.py`
- `docs/evidence/SLICE-049-approval-expiry.txt`

## 修改文件

- `src/adk_agent/core/approval.py`：`expires_at`
- `docs/contracts/approval_request.schema.json`：重新导出
- `src/adk_agent/approvals.py`：过期判定、`ApprovalExpired`、`ttl_seconds`、`on_submit`
- `src/adk_agent/orchestration/executor.py`：填 `expires_at`
- `src/adk_agent/console.py`：410 映射
- `src/adk_agent/cli.py`：`console --approval-ttl`
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ApprovalRequest:
  ...原有字段...
  expires_at: datetime | None   # 必须带时区

FileApprovalInbox(root, *, poll_seconds=0.5, clock=None, ttl_seconds=None, on_submit=None):
  is_expired(request: ApprovalRequest, now: datetime | None = None) -> bool
  pending() -> list[ApprovalRequest]           # 跳过过期项
  decide(...) -> ApprovalDecision              # 过期且未决 -> ApprovalExpired
  request(request) -> ApprovalDecision         # 过期 -> ApprovalExpired；提交后调用 on_submit 一次

ApprovalExpired(ApprovalInboxError)
```

## 完成判据（可执行）

- [ ] 过期请求不进入待决 -> `tests/test_approvals_expiry.py::test_pending_excludes_expired`
- [ ] 决定过期请求抛 `ApprovalExpired` -> `tests/test_approvals_expiry.py::test_decide_expired_raises`
- [ ] 已决过期请求仍是冲突 -> `tests/test_approvals_expiry.py::test_decided_request_is_not_expired`
- [ ] 带 `expires_at` 的门等待直接抛过期 -> `tests/test_approvals_expiry.py::test_gate_raises_when_expired`
- [ ] 请求自带 `expires_at` 优先于 `ttl_seconds` -> `tests/test_approvals_expiry.py::test_request_expiry_wins_over_ttl`
- [ ] 没有 `expires_at` 时用 ttl 兜底 -> `tests/test_approvals_expiry.py::test_ttl_fallback`
- [ ] 没有两者时不过期 -> `tests/test_approvals_expiry.py::test_no_deadline_never_expires`
- [ ] 提交回调被调用 -> `tests/test_approvals_expiry.py::test_on_submit_called`
- [ ] 回调失败不阻止决定 -> `tests/test_approvals_expiry.py::test_on_submit_failure_is_logged`
- [ ] 控制台过期决定返回 410 -> `tests/test_console_approvals_expiry.py::test_decide_expired_returns_410`
- [ ] 列表带 `expires_at` 且不含过期项 -> `tests/test_console_approvals_expiry.py::test_list_excludes_expired`
- [ ] CLI 转发 `--approval-ttl` -> `tests/test_cli_approval_ttl.py::test_console_forwards_approval_ttl`
- [ ] 计划截止时间写入 `expires_at` -> `tests/orchestration/test_approval_expiry.py::test_deadline_sets_expiry`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.approvals import ApprovalExpired` -> 当前 `ImportError`
- [ ] 反例 2：计划步骤带时间上限时 `expires_at` 仍为空 -> 当前确实为空（模型已按契约先加字段）
- [ ] 反例 3：过期的待决请求仍出现在 `pending()` -> 当前确实出现
- [ ] 反例 4：决定过期请求成功 -> 当前确实成功
- [ ] 反例 5：`console --approval-ttl 30` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/`，再改代码。

- `approval_request.schema.json` 加可选 `expires_at`。
- `console.md`：列表不含过期项，过期决定返回 410。
- `cli.md`：`console --approval-ttl`。

## 5 问威胁建模（10 分钟）

1. **数据**：待审输入、截止时间、决定、提交回调。
2. **调用方**：计划执行器、控制台、通知集成。
3. **信任边界**：执行器到收件箱，控制台到收件箱，回调到外部系统。
4. **恶意输入最坏结果**：过期请求被批准（过期后仍执行高风险步骤）；伪造过期时间让审批长期有效；回调把待审输入发给外部。缓解是过期以请求的 `expires_at` 为准并强制执行、时区必填、回调由部署方提供且失败只记日志、审计不含 input。
5. **失败是否泄露信息**：410 只回 `approval_expired`，不带请求内容。回调失败日志只记请求 id 和异常类名。

## 范围外

- 删除和归档已决或已过期的文件。
- 邮件、聊天等具体通知渠道。`on_submit` 是扩展点。
- 审批的续期。
- 多级审批和会签。

## 证据

- 反例红: 待补
- 实现后绿: 待补
