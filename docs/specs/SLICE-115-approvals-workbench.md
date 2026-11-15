# SLICE-115 审批工作台

状态: gated
依据: 审批收件箱已支持跨进程与到期，但控制台只有一行表格和整段 JSON，审批人看不到有效截止时间，也不能填写决定理由。

## 意图（要什么，不写怎么写）

把 Approvals 面板做成审批工作台。列表显示有效截止时间并支持过滤；选中后显示结构化摘要与待审输入；决定时带上理由，成功后该行消失。

- `/api/approvals` 的每条请求返回**有效截止时间**。请求自带 `expires_at` 时原样返回；没有时用收件箱的 TTL 从 `requested_at` 推算；两者都没有时为 `null`。
- 列表增加 expires 列，按浏览器当前时间显示剩余时间；没有截止时间显示固定文案。
- 过滤框按请求 id、步骤、agent 与理由即时过滤，不发起新请求。
- 选中行高亮，摘要显示请求 id、run、trace、步骤、agent、租户、申请时间与截止时间。
- 待审输入用文本节点渲染；合法 JSON 只做缩进，不执行任何标记。
- 决定按钮发送 `{approved, reason}`，理由来自输入框，可为空。
- 成功决定后清空选择、刷新列表，并显示 approved 或 denied 与请求 id。
- 没有待决请求时显示空态文案。

## 新增文件

- `docs/evidence/SLICE-115-approvals-workbench.txt`

## 修改文件

- `src/adk_agent/console.py`（审批列表有效截止时间与工作台渲染）
- `tests/test_console_approvals_expiry.py`（有效截止时间用例）
- `docs/contracts/console.md`（`/api/approvals` 的 `expires_at` 语义）
- `docs/specs/ROADMAP.md`

## 完成判据（可执行）

- [x] 请求没有自带截止时间时，列表返回 `requested_at + TTL` -> `tests/test_console_approvals_expiry.py::test_list_materializes_the_ttl_deadline`
- [x] 请求自带截止时间时不被 TTL 覆盖 -> `::test_list_keeps_an_explicit_deadline`
- [x] 既无 TTL 也无截止时间时返回 `null` -> `::test_list_without_ttl_or_deadline_stays_null`
- [x] 过期请求仍不出现在列表 -> `::test_list_excludes_expired`
- [x] 决定过期请求仍返回 410 -> `::test_decide_expired_returns_410`
- [x] 列表剩余时间、过滤、摘要与理由提交 -> 浏览器证据：三条待决、过滤器把列表缩到一条、摘要字段齐全、决定后行消失
- [x] 待审输入按文本渲染 -> 浏览器证据：含标记的输入显示为字面文本且无脚本执行

## 反例（必须在实现前跑红）

- [x] 反例 1：列表只回传请求 JSON，TTL 截止时间丢失，界面显示“无截止” -> 期望 `::test_list_materializes_the_ttl_deadline` 失败
- [x] 反例 2：用 TTL 覆盖请求自带的截止时间 -> 期望 `::test_list_keeps_an_explicit_deadline` 失败
- [x] 反例 3：过滤器把输入拼进 HTML，标记被执行 -> 期望浏览器证据中无脚本执行
- [x] 反例 4：决定时不带理由，审批记录缺少理由 -> 期望浏览器证据中决定返回的理由与输入一致

红态记录：实现前 `test_list_materializes_the_ttl_deadline` 以 `AttributeError: 'NoneType' object has no attribute 'replace'` 失败，其余两个新用例与原有用例通过。

## 契约（如涉及对外接口）

`docs/contracts/console.md` 先写明 `/api/approvals` 的 `expires_at` 是有效截止时间，再改实现。

## 5 问威胁建模（10 分钟）

1. **数据**：待审输入、请求原因、申请人、决定理由与截止时间。
2. **调用方**：控制台浏览器、审批人、执行器。
3. **信任边界**：审批人到控制台；控制台到收件箱；待审输入到浏览器。
4. **恶意输入最坏结果**：待审输入含脚本导致 XSS（缓解：全部 `textContent`）；跨租户看到别人的审批（缓解：沿用现有 principal 过滤）；过滤器泄露不可见请求（缓解：只过滤已返回的数据）；决定理由被当作审计原文（缓解：审计只记 approver 与 target，不记 input）。
5. **失败是否泄露信息**：列表与决定沿用固定错误码，不返回收件箱路径或文件内容。

## 范围外

- 已决审批的历史列表与撤销。
- 批量审批与键盘快捷键。
- 在审批时预览运行时上下文或重新执行计划。
- 市场卡片改版，另开切片。

## 证据

- 红态、实现后绿、浏览器工作台与门禁结果: `docs/evidence/SLICE-115-approvals-workbench.txt`
