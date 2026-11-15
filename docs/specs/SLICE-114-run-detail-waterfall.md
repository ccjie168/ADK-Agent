# SLICE-114 运行详情瀑布

状态: gated
依据: SLICE-110 已把运行、模型、工具与 A2A span 写入 trace；控制台现有 Trace 只是一行行文本，看不出耗时分布。

## 意图（要什么，不写怎么写）

把 Runs 与 Plans 的 trace 视图升级为瀑布图。每行显示 span 类型、目标、状态、起点、耗时与成本；条带相对根事件时间轴定位，失败与拒绝用颜色区分。点运行行后在看板上方显示该 trace 的汇总。

- 服务端在 `/api/traces` 的每个节点上给出 `start_offset_ms` 与 `duration_ms`，顶层给出 `total_ms`。
- 早于根事件的节点起点夹为 0；缺少 `latency_ms` 的节点时长为 0，但仍占一行。
- 根节点在前，子节点按事件时间正序。
- UI 用文本节点渲染目标名，不拼接 HTML。
- Runs 与 Plans 共用同一个渲染函数，面板各自独立。
- 空 trace、非法 trace id 与跨租户访问保持现有行为。

## 新增文件

- `docs/evidence/SLICE-114-run-detail-waterfall.txt`

## 修改文件

- `src/adk_agent/console.py`（trace 几何字段与瀑布渲染）
- `tests/test_console_trace.py`（几何与边界用例）
- `docs/contracts/console.md`（`/api/traces` 新字段）
- `docs/specs/ROADMAP.md`

## 完成判据（可执行）

- [x] 节点带相对根的起点与时长，顶层带总时长 -> `tests/test_console_trace.py::test_trace_payload_includes_waterfall_geometry`
- [x] 早于根的节点起点夹为 0，总时长按结束时间取最大 -> `::test_trace_payload_clamps_offsets_before_the_root`
- [x] 缺少 `latency_ms` 时时长为 0，起点仍正确 -> `::test_trace_payload_handles_missing_latency`
- [x] 原有根与子节点顺序不变 -> `::test_trace_payload_has_root_and_children`
- [x] 找不到根时仍返回 `trace_not_found` -> `::test_unknown_trace`
- [x] Runs 与 Plans 面板各自渲染瀑布，点运行行显示汇总 -> 浏览器证据：两处 trace 容器出现同样数量的 span 行与时间轴
- [x] 目标名按文本渲染，不执行注入标记 -> 浏览器证据：注入型 target 显示为字面文本

## 反例（必须在实现前跑红）

- [x] 反例 1：子事件早于根时出现负偏移 -> 期望 `::test_trace_payload_clamps_offsets_before_the_root` 失败
- [x] 反例 2：缺失延迟时宽度为 `NaN` 或整行消失 -> 期望 `::test_trace_payload_handles_missing_latency` 失败
- [x] 反例 3：总时长只算根而不算子节点结束时间 -> 期望 `::test_trace_payload_includes_waterfall_geometry` 与 `::test_trace_payload_handles_missing_latency` 覆盖
- [x] 反例 4：注入型 target 被当作 HTML 执行 -> 期望浏览器证据中页面无脚本执行，文字原样显示

红态记录：实现前三个新用例均以 `KeyError: 'start_offset_ms'` 失败，原有四个用例通过。

## 契约（如涉及对外接口）

`docs/contracts/console.md` 先补 `start_offset_ms`、`duration_ms` 与 `total_ms` 的形状和夹取规则，再改实现。

## 5 问威胁建模（10 分钟）

1. **数据**：trace 的事件目标、状态、延迟、成本与时间戳。
2. **调用方**：控制台浏览器、Runs 与 Plans 面板。
3. **信任边界**：审计事件到浏览器渲染；跨租户查询。
4. **恶意输入最坏结果**：target 含脚本导致 XSS（缓解：全部用 `textContent`）；时间戳异常导致除零或 `NaN`（缓解：夹取偏移，总时长为 0 时按固定宽度显示）；跨租户泄露（缓解：沿用现有可见性过滤）。
5. **失败是否泄露信息**：找不到 trace 只返回固定文案，不返回文件路径或查询细节。

## 范围外

- 在浏览器里按 span 下钻查看参数与结果。
- 跨进程 trace 聚合；数据仍来自当前控制台进程的审计查询。
- 火焰图与关键路径分析。
- 审批工作台与市场卡片改版，另开切片。

## 证据

- 红态、实现后绿、浏览器瀑布与门禁结果: `docs/evidence/SLICE-114-run-detail-waterfall.txt`
