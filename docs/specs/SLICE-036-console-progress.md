# SLICE-036 控制台运行进度与 trace 视图（UI）

状态: gated
依据: ADR-0002 第 2、6 条

## 意图（要什么，不写怎么写）

让控制台能看见一次运行的过程，而不只是最后一句回复。

- 运行时在 ADK 事件循环里发结构化进度事件：开始、工具调用、工具结果、模型文本、结束、失败。
- 控制台新增 SSE 端点，边跑边推。
- 页面显示运行状态、计时、进度时间线。
- 运行结束后按 trace_id 拉审计事件，渲染 trace 树。
- 进度回调失败不能影响 agent 运行。
- 旧 `/api/chat` 保留。
- 这一刀不做历史运行列表分页、不做多 agent 计划可视化。

## 新增文件

- `src/adk_agent/core/progress.py`
- `tests/runtime/test_progress.py`
- `tests/test_console_stream.py`
- `tests/test_console_trace.py`
- `docs/contracts/progress_event.schema.json`
- `docs/evidence/SLICE-036-console-progress.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`：导出 `ProgressEvent`
- `src/adk_agent/runtime/execution.py`：`on_progress` 回调
- `src/adk_agent/console.py`：SSE 端点、trace 端点、页面进度面板
- `docs/contracts/console.md`：新端点
- `scripts/export_contracts.py`：导出进度 schema
- `docs/specs/ROADMAP.md`：UI 切片

## 完成判据（可执行）

- [x] 进度事件覆盖开始到结束 -> `tests/runtime/test_progress.py::test_progress_sequence`
- [x] 工具调用与结果可见 -> `::test_progress_reports_tools`
- [x] 回调异常不影响运行 -> `::test_progress_callback_failure_is_ignored`
- [x] SSE 推送进度和完成事件 -> `tests/test_console_stream.py::test_stream_emits_progress_and_done`
- [x] SSE 鉴权 -> `::test_stream_requires_token`
- [x] 策略拒绝返回 403 -> `::test_stream_denied_by_policy`
- [x] trace 端点返回根和子节点 -> `tests/test_console_trace.py::test_trace_after_chat`
- [x] 未知 trace 返回空 -> `::test_unknown_trace`
- [x] 页面有进度面板和 trace 面板 -> `::test_index_has_progress_panels`
- [x] 契约 schema 同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import ProgressEvent` -> 当前 `ImportError`
- [x] 反例 2：`POST /api/chat/stream` -> 当前 404
- [x] 反例 3：`GET /api/traces/{id}` -> 当前 404
- [x] 反例 4：进度回调抛异常 -> 当前会中断运行（期望被忽略）

## 契约

```python
class ProgressEvent(BaseModel):
    kind: Literal["run.started", "tool.call", "tool.result", "model.text",
                  "run.finished", "run.failed"]
    run_id: str
    trace_id: str
    author: str | None = None
    tool: str | None = None
    text: str | None = None
    detail: str | None = None
    elapsed_ms: int | None = None
    timestamp: datetime
```

- `POST /api/chat/stream` 请求同 `/api/chat`。响应 `text/event-stream`。
- 事件是 `event: progress` + JSON，最后是 `event: done`（回复与会话）或 `event: error`。
- 鉴权和策略检查在建立流之前完成，拒绝返回普通 JSON 错误。
- `GET /api/traces/{trace_id}` 返回 `{trace_id, root}`。根是最后一条 `agent.run` 或 `orchestration.run`，子节点是其余事件。
- 找不到根时 `root` 为 `null`。

## 5 问威胁建模（10 分钟）

1. **数据**：输入、回复、工具名、耗时、审计摘要、token。
2. **调用方**：浏览器控制台。
3. **信任边界**：SSE 连接、bearer token、trace_id 路径参数。
4. **恶意输入最坏结果**：匿名读进度；用 trace_id 路径注入；进度流泄漏工具参数或密钥；回调异常拖垮运行。用鉴权、trace_id 正则、只发工具名不发参数、回调异常吞掉并记录处理。
5. **失败是否泄露信息**：SSE 的 error 只给固定文案。trace 只含审计里的 target 和哈希结果。

### 已知边界

- SSE 是单进程内存队列，多副本需要粘性会话或共享事件流。
- 进度只覆盖 agent 运行，不含编排计划的逐步可视化。
- trace 视图是平铺子节点，编排嵌套用现有 `build_trace`，未接 UI。
- 没有运行列表分页和搜索。

## 证据

- 反例红: `ImportError: cannot import name 'ProgressEvent'`，2 个测试模块收集失败
- 实现后绿: 进度、SSE、trace 测试 12 passed
- 真实控制台: SSE 依次推送 run.started / tool.call / tool.result / model.text / run.finished，最后 done
- trace 端点返回根 `agent progress_bot@dev ok`，子节点 tool 与 model
- 旧 `/api/chat` 仍返回 200
- `check.py --fast` -> 357 passed, 2 skipped，7 步全 PASS
- `check.py --full` -> 357 passed, 2 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-036-console-progress.txt`
