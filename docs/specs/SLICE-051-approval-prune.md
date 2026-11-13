# SLICE-051 审批记录归档与删除

状态: spec'd
依据: SLICE-045，SLICE-049，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

审批的请求和决定文件只增不删。这一刀给运维一个显式入口，按保留期归档或删除已经终结的记录。

- `FileApprovalInbox.prune(max_age_seconds, *, archive=True, now=None) -> PruneResult`。
- 只处理终结记录：有决定的用 `decided_at`，没有决定但已过期的用 `expires_at`。没有决定且未过期的请求永远保留。
- 终结时间早于 `now - max_age_seconds` 才处理，等于或晚于保留期不动。
- 默认移动到 `<root>/archive/`，保留原文件名。归档目录里已有同名文件时跳过该条，源文件保留。
- `archive=False` 时删除。
- 先移动或删除请求文件，再处理决定文件。中途崩溃只会留下孤立的决定文件，不会让请求重新变成待决。
- 新增 `adk-agent approvals prune --dir DIR --older-than SECONDS [--delete]`。

这一刀不做定时任务、不做归档目录的二次清理、不写审计事件。

## 新增文件

- `tests/test_approvals_prune.py`
- `tests/test_cli_approvals_prune.py`
- `docs/evidence/SLICE-051-approval-prune.txt`

## 修改文件

- `src/adk_agent/approvals.py`：`PruneResult`、`prune`
- `src/adk_agent/cli.py`：`approvals prune` 子命令
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
PruneResult:
  archived: int
  deleted: int
  kept: int

FileApprovalInbox.prune(max_age_seconds: float, *, archive: bool = True, now: datetime | None = None) -> PruneResult
```

- `now` 缺省用收件箱的 `clock()`。
- 每条请求文件都计入 `kept`、`archived` 或 `deleted` 之一。读不出或校验失败的文件计入 `kept`。
- 归档目标是 `<root>/archive/<id>.request.json` 和 `<root>/archive/<id>.decision.json`。

## 完成判据（可执行）

- [ ] 默认归档旧的决定记录 -> `tests/test_approvals_prune.py::test_archive_moves_terminal`
- [ ] `archive=False` 删除 -> `tests/test_approvals_prune.py::test_delete_removes_terminal`
- [ ] 保留期内的终结记录不动 -> `tests/test_approvals_prune.py::test_recent_terminal_kept`
- [ ] 待决请求不动 -> `tests/test_approvals_prune.py::test_pending_kept`
- [ ] 没有决定但已过期的记录被归档 -> `tests/test_approvals_prune.py::test_expired_without_decision_archived`
- [ ] 没有截止时间的待决请求不动 -> `tests/test_approvals_prune.py::test_no_deadline_pending_kept`
- [ ] 计数正确 -> `tests/test_approvals_prune.py::test_result_counts`
- [ ] 归档后不再出现在待决列表 -> `tests/test_approvals_prune.py::test_archived_request_is_gone`
- [ ] CLI 默认归档 -> `tests/test_cli_approvals_prune.py::test_cli_archives`
- [ ] CLI `--delete` 删除 -> `tests/test_cli_approvals_prune.py::test_cli_deletes`
- [ ] CLI 缺目录退出 1 -> `tests/test_cli_approvals_prune.py::test_cli_requires_dir`
- [ ] CLI 拒绝非正的保留期 -> `tests/test_cli_approvals_prune.py::test_cli_rejects_nonpositive`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.approvals import PruneResult` -> 当前 `ImportError`
- [ ] 反例 2：`FileApprovalInbox.prune` -> 当前没有这个方法
- [ ] 反例 3：`adk-agent approvals prune ...` -> 当前 argparse 退出 2，没有 approvals 子命令
- [ ] 反例 4：归档旧记录后待决列表仍包含它 -> 当前没有归档能力，确实仍在

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`，再改代码。已加 `approvals prune` 一节。

## 5 问威胁建模（10 分钟）

1. **数据**：审批请求、决定、归档文件、保留期。
2. **调用方**：运维和定时任务。
3. **信任边界**：命令行参数到文件系统。
4. **恶意输入最坏结果**：误删未终结的请求，让执行器一直等待；路径穿越写到目录外；归档同名文件被覆盖。缓解是只处理终结记录、文件名只由校验过的请求 id 构成、归档目标已存在时跳过不覆盖、保留期必须为正。
5. **失败是否泄露信息**：命令只输出计数，不输出请求内容。归档和删除失败时异常退出，错误里不带审批内容。

## 范围外

- 定时执行和 cron 配置。
- 归档目录自身的过期清理。
- 审计事件。
- 远程存储归档。

## 证据

- 反例红: 待补
- 实现后绿: 待补
