# SLICE-098 审批的 Postgres 收件箱

状态: merged
依据: ADR-0017 第 1、2、3 条。

## 意图（要什么，不写怎么写）

审批仍用两个文件表示一条请求，跨主机不可靠。这一刀落 Postgres 收件箱，单行状态机与原子决策，语义与文件实现对齐。控制台与执行器的接线留给 099。

- 新增 `PostgresApprovalInbox`，方法改为异步，行为与 `FileApprovalInbox` 对齐。
- 提交幂等，同 id 不同内容冲突；决策用条件 `UPDATE`，并发只有一个成功。
- 过期按 `expires_at` 在读取与决策时判断；已决策的记录保持原决定。
- `pending` 不返回已决策或已过期；`prune` 归档或删除终结记录。
- `request()` 沿用轮询。

## 新增文件

- `src/adk_agent/approvals_postgres.py`
- `tests/test_approvals_postgres.py`
- `docs/evidence/SLICE-098-approvals-postgres.txt`
- `docs/specs/SLICE-098-approvals-postgres.md`

## 修改文件

- `src/adk_agent/approvals.py`（如需要导出共享常量，保持文件实现不变）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
adk_approvals (
  request_id text primary key,
  tenant text not null,
  run_id text not null,
  trace_id text not null,
  step_id text not null,
  agent_ref jsonb not null,
  principal jsonb not null,
  input text not null,
  reason text not null default '',
  requested_at timestamptz not null,
  expires_at timestamptz,
  status text not null,            -- pending | approved | denied | expired | cancelled
  decided_at timestamptz,
  decided_by text,
  decision jsonb
)
索引: (status, requested_at)
adk_approvals_archive: 同列 + archived_at timestamptz not null

PostgresApprovalInbox(url, *, poll_seconds=0.5, clock=None,
                       ttl_seconds=None, on_submit=None)

async submit(request):
  INSERT ... ON CONFLICT (request_id) DO NOTHING
  已存在且内容相同 -> 幂等；不同 -> ApprovalConflict

async decide(request_id, *, approved, approver, reason=""):
  UPDATE ... SET status, decided_at, decided_by, decision
    WHERE request_id=$1 AND status='pending'
      AND (expires_at IS NULL OR expires_at > now())
    RETURNING *
  无返回行时: 不存在 -> ApprovalNotFound；
              已终结 -> ApprovalConflict；
              pending 但过期 -> ApprovalExpired，并把行标成 expired

async get(request_id) -> ApprovalRecord | None
async pending() -> list[ApprovalRequest]   # pending 且未过期，按 requested_at
async prune(max_age_seconds, archive=True) -> PruneResult
async request(request) -> ApprovalDecision # 提交、通知、轮询
```

## 完成判据（可执行）

- [x] 提交幂等与内容冲突 -> `tests/test_approvals_postgres.py::test_submit_idempotent_and_conflict`
- [x] 决策一次成功，第二次冲突 -> `::test_decide_once`
- [x] 过期请求不能决策且被标成 expired -> `::test_expired_cannot_decide`
- [x] `pending` 排除已决策与已过期 -> `::test_pending_filters`
- [x] `get` 返回决定 -> `::test_get_returns_decision`
- [x] 归档与删除 -> `::test_prune_archive_and_delete`
- [x] 并发决策只一个成功 -> `::test_concurrent_decide`
- [x] `request()` 轮询拿到决定 -> `::test_request_polls_to_decision`
- [x] 文件实现行为不变 -> 现有审批测试全绿
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.approvals_postgres import PostgresApprovalInbox` -> 当前 `ModuleNotFoundError`
- [x] 反例 2：`SELECT to_regclass('adk_approvals')` -> 当前为 `null`
- [x] 反例 3：新测试模块在旧代码上收集失败 -> 当前 `ModuleNotFoundError`

## 契约（如涉及对外接口）

本切片只加存储，不改外部接口。控制台与 CLI 的 `--approval-db` 在 099 更新契约。

## 5 问威胁建模（10 分钟）

1. **数据**：请求内容、执行输入、principal、决定、审批人、时间。
2. **调用方**：计划执行器、控制台、CLI 运维。
3. **信任边界**：进程到 Postgres；审批决定到执行放行。
4. **恶意输入最坏结果**：重复决策（缓解：条件 UPDATE，只一个成功）；过期后仍放行（缓解：SQL 谓词带 `expires_at > now()`）；同 id 替换请求内容（缓解：冲突拒绝）；跨租户读取（缓解：服务层过滤，099 接线时校验）；归档丢数据（缓解：同事务先归档再删除）。
5. **失败是否泄露信息**：错误只回固定类型与 request_id；不回显执行输入。

## 范围外

- 控制台与执行器接线（099）。
- RLS。
- `LISTEN/NOTIFY` 唤醒。
- 取消审批的入口（状态已预留）。

## 证据

- 反例红：`docs/evidence/SLICE-098-approvals-postgres.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，真实 Postgres 上并发决策、过期与归档
