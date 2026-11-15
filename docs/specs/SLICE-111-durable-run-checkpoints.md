# SLICE-111 运行检查点与恢复

状态: gated
依据: 调研记录 `docs/research/agent-framework-landscape.md`；参考 LangGraph、Microsoft Agent Framework 与 DBOS 的 durable 语义。

## 意图（要什么，不写怎么写）

把运行状态、步骤结果与待审批点存进 Postgres，进程重启后从断点继续，不重复执行副作用。审批从“收件箱消息”升级为可恢复的 interrupt。

- 每次运行有 `run_id`，步骤结果按顺序写成检查点记录，状态包括 running、waiting_approval、completed、cancelled、failed。
- 已完成的步骤在恢复时跳过，不重复调用 agent。步骤内部的工具重放不在 v1 范围，失败步骤按重试语义重新执行。
- 审批暂停时保存等待步骤；批准后从等待步骤继续。没有审批入口时记为 waiting_approval，下次带审批入口重跑即可恢复。
- 检查点按租户隔离，Postgres 表启用 RLS，服务层同时按租户过滤。
- 计划摘要不匹配、取消后恢复、损坏记录一律拒绝，不猜测恢复。
- v1 覆盖 single 与 sequential 计划；fan_out、routing、supervisor 保持现有行为。

## 新增文件

- `src/adk_agent/orchestration/checkpoints.py`
- `tests/orchestration/test_checkpoints.py`
- `tests/orchestration/test_postgres_checkpoints.py`
- `docs/evidence/SLICE-111-durable-run-checkpoints.txt`

## 修改文件

- `src/adk_agent/orchestration/executor.py`（顺序执行器的检查点读写）
- `src/adk_agent/orchestration/__init__.py`（导出）

## 完成判据（可执行）

- [x] 完成两步后停止进程，重启后从第三步继续并完成 -> `tests/orchestration/test_checkpoints.py::test_resume_after_failure`
- [x] 已完成的步骤不会重跑，第三次运行直接返回结果 -> 同文件 `::test_resume_after_failure`
- [x] 审批暂停后批准，运行从等待步骤继续 -> `::test_approval_wait_resumes`
- [x] 取消后恢复请求被拒绝 -> `::test_cancelled_checkpoint_is_terminal`
- [x] 计划摘要不匹配时拒绝恢复 -> `::test_plan_digest_mismatch_fails_closed`
- [x] 检查点按租户隔离 -> `::test_store_is_tenant_scoped` 与 `tests/orchestration/test_postgres_checkpoints.py::test_roundtrip_and_tenant_scope`
- [x] 没有 URL 时使用内存存储，非法 URL 被拒绝 -> `::test_build_picks_in_memory` / `::test_build_rejects_unknown_dsn`

## 反例（必须在实现前跑红）

- [x] 反例 1：停在第 2 步后重启，步骤 a 与 b 被重复调用 -> 期望 `::test_resume_after_failure` 的调用数断言失败
- [x] 反例 2：用租户 A 的 run_id 在租户 B 读取 -> 期望零行，而不是数据泄露
- [x] 反例 3：计划摘要不匹配的检查点被接受 -> 期望 `checkpoint_corrupt` 并停止恢复
- [x] 反例 4：已取消的运行收到恢复请求 -> 期望拒绝

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
- 步骤内部工具调用的幂等键。失败步骤按重试语义重新执行，工具需要自身幂等或走审批。
- fan_out、routing、supervisor 的检查点。
- 把执行器迁移到 Temporal 或 Conductor。
- 无限制的历史检查点保留。保留与 GC 单独评审。
- 服务入口接线。执行器目前是库能力，计划入口落地时再接检查点存储。

## 证据

- 反例红、实现后绿与门禁结果: `docs/evidence/SLICE-111-durable-run-checkpoints.txt`
