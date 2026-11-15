# SLICE-119 运行详情下钻

状态: gated
依据: SLICE-114 的瀑布只显示几何与状态。点中一个 span 没有反应，解释这一段的审计字段（动作、目标、策略版本、参数哈希、token 与出站标记）也没有进 payload。运行出问题时，运营只能看到一条红条，看不到为什么。

## 意图（要什么，不写怎么写）

让瀑布支持下钻。点中或键盘选中一个 span，在瀑布下方显示这一段的审计字段。

- trace 节点增量携带审计字段，不新增接口。
- 瀑布行可点击，也支持 Enter 与 Space。选中行写 `aria-pressed="true"` 并高亮。
- 详情面板显示动作、目标、状态、错误码、起止、延迟、成本、token、租户、主体、审批人、agent、参数哈希、结果哈希、策略、数据分级、出站标记、事件与运行 id。
- 详情初始提示选择一段，加载新 trace 时清空。
- Runs 与 Plans 共用同一渲染，两处都能下钻。
- 所有动态文本用 `textContent`。不展示 prompt、completion 或工具参数原文。

## 数据形状

`_trace_node(event)` 是 AuditEvent 到节点的唯一映射，增量补充字段。前端用一张字段描述表 `TRACE_DETAIL_FIELDS`（label 取值函数）渲染详情，不写一长串手写赋值。

```json
{
  "event_id": "e1", "run_id": "r1", "action": "tool.call", "target": "crm.read",
  "tenant": "acme", "principal": {"subject": "alice", "kind": "human"},
  "agent": {"id": "support-bot", "version": "1.0.0"},
  "approver": null, "args_hash": "sha256:...", "result_hash": null,
  "policy_decision_id": "d1", "policy_version": "rbac:3",
  "data_classes": ["internal"], "tokens": 42, "egress": "third_party"
}
```

## 新增文件

- `tests/test_console_trace_detail.py`
- `docs/evidence/SLICE-119-run-drilldown.txt`
- `docs/evidence/ui/SLICE-119-run-drilldown.png`

## 修改文件

- `src/adk_agent/console.py`（节点字段、可选中的瀑布行、详情面板）
- `docs/contracts/console.md`
- `docs/decisions/ADR-0022-self-service-composition.md`（后续切片不再预分配编号）
- `docs/specs/ROADMAP.md`
- `docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 节点带契约列出的审计字段 -> `tests/test_console_trace_detail.py::test_node_carries_audit_fields`
- [x] 空值保持 `null`，`data_classes` 是数组 -> `::test_node_keeps_null_fields`
- [x] payload 不含 prompt、completion、参数原文 -> `::test_payload_has_no_raw_content`
- [x] 点击 span 后详情显示对应字段 -> 浏览器证据
- [x] Enter 与 Space 也能选中，`aria-pressed` 随之变化 -> 浏览器证据
- [x] Runs 与 Plans 两处都能下钻 -> 浏览器证据
- [x] 标记文本按字面显示，不执行脚本 -> 浏览器证据
- [x] 加载新 trace 时详情清空并回到提示态 -> 浏览器证据
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：节点缺审计字段，下钻没有内容 -> 期望 `::test_node_carries_audit_fields` 失败
- [x] 反例 2：详情用 `innerHTML` 渲染，标记被执行 -> 期望浏览器证据中 `window.__trace_xss` 未设置
- [x] 反例 3：只能鼠标选中，键盘无效 -> 期望浏览器证据中按 Enter 后 `aria-pressed` 为 true
- [x] 反例 4：Plans 面板没有详情 -> 期望浏览器证据中 Plans 的下钻可用
- [x] 反例 5：payload 带 prompt 或参数原文 -> 期望 `::test_payload_has_no_raw_content` 失败

红态记录: 实现前 `pytest tests/test_console_trace_detail.py -q` 为 3 failed, 1 passed。字段断言失败，空值用例在 `approver` 上 KeyError，传播用例在 `event_id` 上 KeyError。原文用例在红态下本就通过，作为回归守卫保留。

## 契约（如涉及对外接口）

先合并 `docs/contracts/console.md` 的节点字段说明，再改实现。

## 5 问威胁建模（10 分钟）

1. **数据**：审计字段，包含动作、目标、主体、策略版本、哈希、token、成本与出站标记。不含原文。
2. **调用方**：控制台运营与管理员。
3. **信任边界**：审计存储到控制台；控制台到浏览器。
4. **恶意输入最坏结果**：target 或 error_code 注入脚本导致 XSS（缓解：全部 `textContent`）；跨租户看到别人的 span（缓解：沿用 `_visible_events` 过滤）；泄露 prompt 或参数原文（缓解：payload 不带这些字段）；详情字段过多拖慢页面（缓解：字段固定，数量有界）。
5. **失败是否泄露信息**：沿用 trace 的固定错误码，不返回存储路径。

## 范围外

- 展示 prompt、completion 或工具参数原文。
- 重跑单个 span、导出 trace、按字段过滤 span。
- 跨 run 搜索与对比。
- 修改审计字段本身。

## 证据

- 红态、实现后绿、浏览器下钻与门禁结果: `docs/evidence/SLICE-119-run-drilldown.txt`
- 详情面板截图: `docs/evidence/ui/SLICE-119-run-drilldown.png`
