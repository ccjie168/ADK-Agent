# SLICE-127 调度循环与重试

状态: gated
依据: ADR-0022 决定 6。定时触发需要一个调度循环，按租户计配额、写审计、具备幂等与重试，只调用 pinned 版本，触发器不允许内联脚本。本切片补上 schedule 路径与上车重试，不改 webhook 语义。

## 意图（要什么，不写怎么写）

`serve-triggers` 内置调度循环。每个 tick 检查所有启用的 schedule 触发，按 `every_seconds` 计算当前 slot，用 fire store 的幂等键保证同一 slot 只运行一次，多副本也只有一个赢家。

- slot 键是 `slot-<unix_slot>`，其中 `unix_slot = floor(now.timestamp() / every_seconds)`。
- 只跑当前 slot。停机错过的 slot 不补跑，避免恢复时的突发。
- 运行路径与 webhook 共用同一套校验、验签、配额、审计与审批拒绝。空的运行输入会被拒绝并记 `invalid_request`。
- webhook 与 schedule 都复用同一个执行函数，避免两条路径漂移。
- 预运行失败（注册表或生命周期读取异常、工件验签或加载异常）最多尝试 `--trigger-attempts` 次，按尝试次数线性退避。确定性的 404、digest 不符、退役与需审批拒绝不重试。agent 已经开始运行后不再自动重试，避免重复副作用。
- 调度循环随应用启动，随关闭优雅停止；`--no-scheduler` 可只开 webhook。
- 循环只读触发与注册表，不修改触发定义。

## 数据形状

不新增记录类型。复用 `TriggerFire` 与 `TriggerFireStore`：

- schedule 的 `idempotency_key` 是 `slot-<n>`，符合既有 `^[A-Za-z0-9._-]{1,128}$`。
- 运行状态与错误码沿用 webhook 路径。

执行结果统一成内部结果对象：

- `TriggerExecution(status: "ok"|"error"|"denied", error_code: str | None, run_id, trace_id, text)`
- `_execute(trigger, input_text, *, fire, run_id, trace_id, attempts)` 负责校验、加载、运行、配额、审计与 finish。
- webhook 把结果映射成 HTTP；调度只记日志与审计。

## 新增文件

- `tests/test_trigger_scheduler.py`
- `docs/evidence/SLICE-127-trigger-scheduler.txt`

## 修改文件

- `src/adk_agent/triggers_service.py`（执行函数抽取、调度循环、lifespan、重试）
- `src/adk_agent/cli.py`（`--schedule-tick`、`--no-scheduler`、`--trigger-attempts`）
- `docs/contracts/trigger_service.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 到期触发在一个 slot 内只运行一次 -> `tests/test_trigger_scheduler.py::test_slot_runs_once`
- [x] 停用与非 schedule 触发被跳过 -> `::test_disabled_and_webhook_triggers_are_skipped`
- [x] 多副本共享 fire store，同一 slot 只有一个赢家 -> `::test_slot_has_one_winner`
- [x] 预运行加载失败按次数重试，耗尽后记 error -> `::test_pre_run_failures_are_retried`
- [x] agent 运行失败不重试 -> `::test_agent_failures_are_not_retried`
- [x] webhook 与调度共用同一执行函数 -> `tests/test_triggers_service.py` 全部保持通过
- [x] 关闭时调度任务被取消 -> `::test_scheduler_stops_on_shutdown`
- [x] CLI 参数校验 -> `tests/test_cli_triggers_service.py` 新增用例
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：同一 slot 运行两次 -> 期望 `::test_slot_runs_once` 失败
- [x] 反例 2：加载失败无限重试 -> 期望 `::test_pre_run_failures_are_retried` 失败
- [x] 反例 3：agent 失败也重试，重复副作用 -> 期望 `::test_agent_failures_are_not_retried` 失败
- [x] 反例 4：调度跳过启用与类型过滤 -> 期望 `::test_disabled_and_webhook_triggers_are_skipped` 失败

红态记录: 实现前调度测试报 `cannot import name 'TriggerExecution'`，CLI 报三个新参数无法识别。

## 5 问威胁建模（10 分钟）

1. **数据**：schedule 触发、interval、slot 键、固定输入、agent 引用。
2. **调用方**：`serve-triggers` 进程内的循环；多副本共享 Postgres 或文件 fire store。
3. **信任边界**：时钟到 slot 计算；fire store 到运行唯一性；注册表到执行。
4. **恶意输入最坏结果**：同一 slot 在多副本重复运行（缓解：fire store claim 单赢家）；停机恢复补跑造成突发（缓解：只跑当前 slot）；重试放大副作用（缓解：只在 agent 启动前重试）；禁用触发仍运行（缓解：每 tick 重新读取并过滤）；时钟回拨造成重复或跳过（缓解：slot 键只依赖当前时间戳，重复会被 claim 挡住；跳过可接受并记录）。
5. **失败是否泄露信息**：日志只记触发 id、slot 与错误码，不记输入原文或令牌。

## 范围外

- cron、时区、错过 slot 的补跑。
- 分布式领导者选举；多副本唯一性由 fire store 保证。
- 触发定义修改与热加载。
- agent 失败后的自动重跑；需要时由下一次 slot 或调用方重试。
- webhook 自动重试；调用方用幂等键重试。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-127-trigger-scheduler.txt`
- 契约: `docs/contracts/trigger_service.md`
