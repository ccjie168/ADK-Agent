# SLICE-099 审批数据库接线

状态: merged
依据: ADR-0017 第 1、2、4、5 条与 SLICE-098 的 `PostgresApprovalInbox`。

## 意图（要什么，不写怎么写）

098 有了共享的审批存储，但控制台仍在用文件收件箱，CLI 的 prune 也只认目录。这一刀把两条运维路径接到 Postgres，让审批在不同主机与副本之间可见。文件实现保留，用于单机与回滚。

- 控制台新增 `--approval-db URL`，与 `--approval-dir` 二选一。显式 `--approval-db` 优先于环境变量 `ADK_APPROVAL_DIR`；显式 `--approval-dir` 优先于 `APPROVAL_DATABASE_URL`；两个显式 flag 同时给出退出 1。
- 控制台对同步与异步收件箱都能工作：调用结果是可等待对象时 await。数据库不可达时审批接口返回 503 `approval_unavailable`。
- `--approval-ttl` 对两种存储都生效；DB 存储把派生出的 `expires_at` 写入行。
- `approvals prune` 新增 `--db URL`，环境变量回退 `APPROVAL_DATABASE_URL`；`--db` 与 `--dir` 二选一，显式 `--db` 忽略 `ADK_APPROVAL_DIR`。
- 执行器不需要改代码：`PostgresApprovalInbox.request()` 已经满足 `ApprovalGate`。新增跨实例测试证明一个进程提交并等待、另一个进程决策后返回。
- 控制台退出时尽力关闭数据库连接池，跨事件循环的关闭失败被忽略。

## 新增文件

- `tests/test_cli_approval_db.py`
- `tests/test_console_approvals_postgres.py`
- `docs/evidence/SLICE-099-approval-db-wiring.txt`
- `docs/specs/SLICE-099-approval-db-wiring.md`

## 修改文件

- `src/adk_agent/cli.py`（console 与 approvals prune 的后端选择）
- `src/adk_agent/console.py`（异步收件箱、503 映射、类型收口）
- `tests/test_approvals_postgres.py`（跨实例 request 测试）
- `docs/contracts/cli.md`、`docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
console --approval-db postgresql://...   # 或 APPROVAL_DATABASE_URL
console --approval-dir DIR               # 或 ADK_APPROVAL_DIR
  -> 显式 flag 先解析；两个显式 flag 同时出现 -> 退出 1
  -> 都没配置 -> 审批接口 404 approvals_not_configured

approvals prune (--dir DIR | --db URL) --older-than SECONDS [--delete]
  -> 显式 --db 时忽略 ADK_APPROVAL_DIR
  -> 两个显式 flag 同时出现 -> 退出 1
  -> 都没有 -> 退出 1

GET  /api/approvals         -> 200 列表 | 404 未配置 | 503 approval_unavailable
POST /api/approvals/{id}    -> 200 决定 | 404 | 409 | 410 | 403 | 503
```

## 完成判据（可执行）

- [x] 控制台显式 flag 互斥与优先级 -> `tests/test_cli_approval_db.py::test_console_approval_backend_exclusive`
- [x] 控制台对异步收件箱列表和决策 -> `tests/test_console_approvals_postgres.py::test_console_awaits_async_inbox`
- [x] 数据库不可达映射 503 -> `::test_console_maps_unavailable_to_503`
- [x] `prune --db` 在真实 Postgres 上归档 -> `tests/test_cli_approval_db.py::test_prune_db_archives`
- [x] `prune` 后端互斥与 env 回退 -> `::test_prune_backend_resolution`
- [x] 跨实例 request 拿到另一实例的决定 -> `tests/test_approvals_postgres.py::test_request_sees_decision_from_another_inbox`
- [x] 文件模式回归 -> 现有审批与控制台测试全绿
- [x] `python scripts/check.py --full` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`console --approval-db URL` -> 当前 argparse `unrecognized arguments`，退出 2
- [x] 反例 2：`approvals prune --db URL` -> 当前 argparse `unrecognized arguments`，退出 2
- [x] 反例 3：给控制台一个只返回协程的异步收件箱 -> 当前列表接口返回 500 或错误形状
- [x] 反例 4：异步收件箱抛 `ApprovalInboxUnavailable` -> 当前 500，不是 503

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md` 与 `docs/contracts/console.md`：后端选择、环境变量优先级、503 错误码。契约合并后再改代码。

## 5 问威胁建模（10 分钟）

1. **数据**：审批请求、待审输入、决定、审批人、租户。
2. **调用方**：控制台操作员、CLI 运维、计划执行器。
3. **信任边界**：进程到 Postgres；审批决定到执行放行。
4. **恶意输入最坏结果**：跨租户决策（缓解：控制台按 token 租户过滤，非 admin 拒绝他人租户；DB 层无 RLS 是已知限制）；伪造后端混淆文件与数据库（缓解：显式 flag 优先、互斥退出）；数据库故障时误放行（缓解：503，不放行）。
5. **失败是否泄露信息**：503 只回固定错误码；不回显 DSN 或执行输入。

## 范围外

- RLS（与审计一致，留后续加固）。
- 多副本 K8s 清单与运维手册（下一刀）。
- `LISTEN/NOTIFY`。
- 控制台提交审批（执行器负责提交）。

## 证据

- 反例红：`docs/evidence/SLICE-099-approval-db-wiring.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，两个进程共享一个 Postgres 审批
