# SLICE-111 运行检查点与恢复

状态: planned
依据: 调研记录 `docs/research/agent-framework-landscape.md`；参考 LangGraph、Microsoft Agent Framework 与 DBOS 的 durable 语义。

## 意图（要什么，不写怎么写）

把运行状态、步骤结果与待审批点存进 Postgres，进程重启后从断点继续，不重复执行副作用。审批从“收件箱消息”升级为可恢复的 interrupt。

- 每次运行有 `run_id`，步骤结果按顺序写成检查点记录，状态包括 running、waiting_approval、resuming、completed、cancelled、failed。
- 工具调用带幂等键，重放时返回已记录结果，不重复执行。
- 审批暂停时保存完整上下文；批准或拒绝后从等待步骤继续。
- 检查点按租户隔离，开启 RLS 时由策略强制。
- 损坏的检查点或非法状态转换一律拒绝，不猜测恢复。

## 新增文件

- `src/adk_agent/orchestration/checkpoints.py`
- `src/adk_agent/orchestration/postgres_checkpoints.py`
- `tests/orchestration/test_checkpoints.py`
- `tests/orchestration/test_postgres_checkpoints.py`

## 修改文件

- `src/adk_agent/orchestration` 的执行器与审批等待点
- `src/adk_agent/cli.py`（可选的管理命令）
- `docs/guides/operations.md`（表结构与恢复步骤）

## 完成判据（可执行）

- [ ] 完成两步后停止进程，重启后从第三步继续并完成 -> `tests/orchestration/test_checkpoints.py::test_resume_after_restart`
- [ ] 重放不会重复执行工具，返回已记录结果 -> `::test_tool_replay_is_idempotent`
- [ ] 审批暂停后批准，运行从等待步骤继续 -> `::test_approval_resumes_run`
- [ ] 审批过期或拒绝后不再恢复 -> `::test_expired_or_denied_does_not_resume`
- [ ] 取消后恢复请求被拒绝 -> `::test_cancel_is_terminal`
- [ ] 损坏的检查点返回 `checkpoint_corrupt` -> `::test_corrupt_checkpoint_fails_closed`
- [ ] 开启 RLS 时跨租户读为零行 -> `tests/orchestration/test_postgres_checkpoints.py::test_tenant_isolation`

## 反例（必须在实现前跑红）

- [ ] 反例 1：停在第 2 步后重启，工具被调用两次 -> 期望 `::test_tool_replay_is_idempotent` 失败
- [ ] 反例 2：用租户 A 的 run_id 在租户 B 读取 -> 期望零行，而不是数据泄露
- [ ] 反例 3：检查点 JSON 被截断 -> 期望 `checkpoint_corrupt` 并停止恢复
- [ ] 反例 4：已取消的运行收到恢复请求 -> 期望拒绝

## 契约（如涉及对外接口）

不新增平台 API。新增 Postgres 表与状态机，表结构写进运维手册；若未来暴露查询接口，先补 `docs/contracts/`。

## 5 问威胁建模（10 分钟）

1. **数据**：运行状态、步骤输入输出、工具结果、审批上下文。
2. **调用方**：执行器、审批接口、恢复命令、运维。
3. **信任边界**：租户之间；进程崩溃与并发恢复之间。
4. **恶意输入最坏结果**：跨租户读取检查点（缓解：RLS 与服务层双过滤）；重放导致重复副作用（缓解：幂等键与结果回放）；损坏状态被误恢复（缓解：失败即停止）；检查点写入 PII（缓解：沿用数据分级与脱敏策略）。
5. **失败是否泄露信息**：错误码只暴露状态，不返回检查点内容或内部路径。

## 范围外

- 分布式事务与跨服务 saga。
- 把执行器迁移到 Temporal 或 Conductor。
- 无限制的历史检查点保留。保留与 GC 单独评审。

## 证据

- 反例红: 待实现
- 实现后绿: 待实现
