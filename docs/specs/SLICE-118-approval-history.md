# SLICE-118 审批历史

状态: gated
依据: SLICE-115 把审批面板做成工作台，但只列待决请求。决定落盘或入库后没有入口回看，`approvals prune` 归档后更不可见。审批人无法回答“上一条类似请求是谁、按什么理由批的”。

## 意图（要什么，不写怎么写）

新增审批历史，覆盖已决、已过期与已归档记录，文件与 Postgres 两个后端语义一致。

- 新增 `ApprovalHistoryEntry`，包含请求、决定、状态、是否归档与终结时间。
- 状态取 `approved`、`denied`、`expired`、`cancelled`。没有决定且未过期的待决请求不出现。
- 文件后端扫描根目录与 `archive/` 子目录。Postgres 后端合并 `adk_approvals` 与 `adk_approvals_archive`，live 的过期 pending 行按 `expired` 返回。
- 按终结时间倒序，`limit` 夹在 1 到 200。`status` 可选过滤。
- `GET /api/approvals/history` 按租户过滤，非 `admin` 只看自己的租户。
- Approvals 面板增加 History 区，含刷新、状态过滤与表格。不引入新的能力名，沿用 `approvals.read`。

## 数据形状

`src/adk_agent/approvals.py` 新增冻结 dataclass 与状态常量：

```python
HISTORY_STATUSES = ("approved", "denied", "expired", "cancelled")

@dataclass(frozen=True)
class ApprovalHistoryEntry:
    request: ApprovalRequest
    decision: ApprovalDecision | None
    status: str
    archived: bool
    terminal_at: datetime
```

两个后端各加一个方法，签名一致：

```python
def history(self, *, tenant: str | None = None, status: str | None = None,
            limit: int = 50) -> list[ApprovalHistoryEntry]: ...      # 文件
async def history(self, *, tenant: str | None = None, status: str | None = None,
                  limit: int = 50) -> list[ApprovalHistoryEntry]: ...  # Postgres
```

`ApprovalGate` 端口不改，执行器不需要历史。未知状态抛 `ValueError`，控制台映射为 400。

## 新增文件

- `tests/test_approvals_history.py`
- `tests/test_approvals_history_postgres.py`
- `tests/test_console_approvals_history.py`
- `docs/evidence/SLICE-118-approval-history.txt`
- `docs/evidence/ui/SLICE-118-approval-history.png`

## 修改文件

- `src/adk_agent/approvals.py`（历史类型与文件后端）
- `src/adk_agent/approvals_postgres.py`（历史查询，合并归档表）
- `src/adk_agent/console.py`（历史接口与 History 区）
- `docs/contracts/console.md`
- `docs/decisions/ADR-0022-self-service-composition.md`（后续切片编号顺延，审批历史占用 118）
- `docs/specs/ROADMAP.md`
- `docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 文件后端列出已决记录，状态与决定一致 -> `tests/test_approvals_history.py::test_decided_records_are_listed`
- [x] 过期未决记录按 `expired` 列出 -> `::test_expired_record_is_listed`
- [x] 未过期的待决记录不出现 -> `::test_pending_record_is_excluded`
- [x] 归档目录中的记录仍然可见，`archived` 为 true -> `::test_archived_records_are_included`
- [x] 租户过滤与状态过滤生效 -> `::test_tenant_and_status_filters`
- [x] 按终结时间倒序并遵守 limit -> `::test_order_and_limit`
- [x] Postgres 合并 live 与 archive，live 过期 pending 记 `expired` -> `tests/test_approvals_history_postgres.py`
- [x] 接口按租户过滤，非法状态 400，limit 夹紧 -> `tests/test_console_approvals_history.py`
- [x] 面板有 History 区与状态过滤 -> 浏览器证据
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：没有历史接口，决定后无法回看 -> 期望控制台历史用例在 `GET /api/approvals/history` 上失败
- [x] 反例 2：归档记录被漏掉，prune 后历史变少 -> 期望 `::test_archived_records_are_included` 失败
- [x] 反例 3：live 的过期 pending 行按 `pending` 返回 -> 期望 Postgres 用例失败
- [x] 反例 4：非 admin 能看到别的租户历史 -> 期望租户过滤用例失败
- [x] 反例 5：状态过滤接受任意字符串 -> 期望 400 用例失败

红态记录: 实现前 `pytest tests/test_approvals_history.py tests/test_console_approvals_history.py -q` 为 12 failed。文件用例在 `FileApprovalInbox.history` 上 AttributeError，控制台用例在 `GET /api/approvals/history` 上失败，页面缺少 `approval-history-body`。

## 契约（如涉及对外接口）

先合并 `docs/contracts/console.md` 的 `GET /api/approvals/history` 一节，再改实现。

## 5 问威胁建模（10 分钟）

1. **数据**：审批请求的待审输入、决定理由、审批人、租户与时间。
2. **调用方**：控制台审批人、租户管理员。
3. **信任边界**：审批存储到控制台；控制台到浏览器。
4. **恶意输入最坏结果**：跨租户读取历史（缓解：服务端按 `request.principal.tenant` 过滤，admin 例外）；待审输入含脚本导致 XSS（缓解：全部 `textContent`）；归档文件损坏导致接口 500（缓解：跳过不可解析记录，与 pending 一致）；历史数据量拖垮接口（缓解：limit 上限 200）。
5. **失败是否泄露信息**：返回固定错误码，不返回存储路径或文件内容。

## 范围外

- 撤销、重新决定与批量导出。
- 跨租户审批历史的管理员检索界面。
- 保留期与归档策略调整。
- 历史记录的审计事件（读取不写审计，与待决列表一致）。
- 按审批人或时间范围的筛选。

## 证据

- 红态、实现后绿、浏览器历史区与门禁结果: `docs/evidence/SLICE-118-approval-history.txt`
- 历史区截图: `docs/evidence/ui/SLICE-118-approval-history.png`
