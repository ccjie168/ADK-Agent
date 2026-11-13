# SLICE-057 SSE 慢客户端与有界进度队列

状态: merged
依据: SLICE-036，SLICE-056，`docs/contracts/console.md`，`docs/contracts/cli.md`。

## 意图（要什么，不写怎么写）

控制台的 `/api/chat/stream` 用一个无界 `asyncio.Queue` 缓冲进度事件。客户端读得慢时队列无限增长，内存跟着运行时长走。这一刀把进度缓冲改成有界，丢弃最旧的 `progress`，终结事件永远保留，并给出可复现的测量。

- `src/adk_agent/console.py` 新增 `ProgressBuffer`，容量参数是 `max_progress`。
- 满时同步丢最旧的一条 `progress` 再入队。终结事件（`done` / `error` / `__end__`）不入这个上限，永不被丢。
- `ProgressBuffer` 自己统计 `dropped` 和 `peak_depth`。
- 流结束时把 `dropped` 放进 `done` 或 `error` 的数据里。
- `build_console_app` 和 `run_console` 增加 `sse_queue_size`（默认 512）。CLI 增加 `--sse-queue-size`。
- `scripts/loadtest.py` 增加 `sse` 子命令，模拟一次产生 N 条进度、客户端每条延迟读取的场景，报告投递数、丢弃数、队列等待分位和峰值深度。

`progress` 被丢是允许的，UI 是观测面不是事实来源。审计不受影响。

## 新增文件

- `tests/test_console_sse_buffer.py`
- `docs/evidence/SLICE-057-sse-backpressure.txt`

## 修改文件

- `src/adk_agent/console.py`：`ProgressBuffer`、`build_console_app`、`run_console`、流路由
- `src/adk_agent/cli.py`：`--sse-queue-size`
- `scripts/loadtest.py`：`sse` 子命令
- `tests/test_loadtest.py`：`sse` 场景用例
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ProgressBuffer(max_progress: int)
  put_progress(payload: dict) -> None      # 满时丢最旧 progress，dropped += 1
  await put_terminal(kind, payload)        # 不丢，数据里补 "dropped"
  await get() -> (kind, payload)
  dropped: int
  peak_depth: int
  depth: int

done / error 数据:
  {..., "dropped": int}

loadtest sse 报告:
  scenario="sse", requests=N, ok=投递数, denied=丢弃数,
  queue_size, peak_depth, latency_ms = 每条投递的排队等待
```

## 完成判据（可执行）

- [x] 满时丢最旧，保留最新 -> `tests/test_console_sse_buffer.py::test_buffer_drops_oldest_progress`
- [x] 终结事件不占上限且带 `dropped` -> `tests/test_console_sse_buffer.py::test_terminal_is_never_dropped`
- [x] 峰值深度不超过上限 -> `tests/test_console_sse_buffer.py::test_peak_depth_is_bounded`
- [x] 容量小于 1 被拒 -> `tests/test_console_sse_buffer.py::test_buffer_rejects_bad_size`
- [x] 流路由用有界缓冲并在 `done` 里报 `dropped` -> `tests/test_console_sse_buffer.py::test_stream_reports_dropped`
- [x] 控制台 `--sse-queue-size 0` 退出 1 -> `tests/test_console_sse_buffer.py::test_console_rejects_zero_queue`
- [x] 慢消费者场景投递数等于上限、丢弃数守恒 -> `tests/test_loadtest.py::test_sse_slow_consumer_drops_oldest`
- [x] 消费者跟得上时不丢 -> `tests/test_loadtest.py::test_sse_fast_consumer_keeps_all`
- [x] `sse` CLI 输出报告 -> `tests/test_loadtest.py::test_cli_sse_report`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.console import ProgressBuffer` -> 当前 `ImportError`
- [x] 反例 2：`console --sse-queue-size 0` -> 当前 argparse 退出 2（参数不存在）
- [x] 反例 3：`loadtest sse --events 10` -> 当前 argparse 退出 2（子命令不存在）

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/console.md` 的流式一节和 `docs/contracts/cli.md` 的控制台一节。

## 5 问威胁建模（10 分钟）

1. **数据**：进度事件的文本片段可能含模型输出；`dropped` 是计数。
2. **调用方**：浏览器控制台和任何拿 bearer token 的 SSE 客户端。
3. **信任边界**：模型产生的进度文本进浏览器；客户端读速由调用方控制。
4. **恶意输入最坏结果**：慢客户端让内存随运行时长无界增长（现状）；丢进度被误当成丢审计。缓解是有界缓冲加 `dropped` 显式计数；审计链与这个队列无关。`max_progress` 非法值（0 或负数）会让每条事件都丢，因此在构造器和 CLI 两处拒绝。
5. **失败是否泄露信息**：报告和 `dropped` 只有计数，不含进度内容。

## 范围外

- 对客户端限速或断开慢连接。丢进度已经封顶内存。
- 进度事件落盘和补发。
- MCP 和 A2A 的流式输出。

## 证据

- 反例红: `docs/evidence/SLICE-057-sse-backpressure.txt` 的 red 段
- 实现后绿: 同文件 green 段，30 passed（含既有 SSE 与配额流用例）
- 实机: 同文件 live 段。真 uvicorn 控制台队列 16，慢客户端收 1199 条、丢 3804 条、终结事件完整送达；`sse` 场景 10000 条突发只保留 256 条，峰值 257，不变量全成立
