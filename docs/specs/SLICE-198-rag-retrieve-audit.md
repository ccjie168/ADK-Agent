# SLICE-198 rag.retrieve 审计

状态: gated
依据: ADR-0036（Accepted 2026-11-20）决定 7 / 切片 3。

## 意图

1. `RagContext` 每次预取写一条 `rag.retrieve` 审计：租户、run、agent、`top_k`、返回条数、被过滤条数、
   状态与 `error_code`、延迟；不记查询原文与片段。
2. `AuditEvent` 新增可选 `rag_top_k`、`rag_returned`、`rag_filtered`（非负），只在检索事件上有值；
   重生成审计两个 schema。
3. 失败语义与审计一致：`deny` 先写 `status=error` 再抛 `RagUnavailable`；`degrade` 写 `status=error`
   后返回空串。成功写 `status=ok` 并带三个计数。

## 契约（先改）

- `docs/contracts/rag_service.md` 增加「检索审计（ADR-0036）」一节：事件字段、过滤计数的定义
  （ACL 丢弃 + 守卫丢弃 + 截断超出 `top_k` 的部分）、不记录内容。
- `docs/contracts/audit_event.schema.json` 与 `docs/contracts/audit_record.schema.json` 重生成。

## 完成判据

- [x] 成功时写一条带计数的 `rag.retrieve` -> `test_rag_context_audits_success`
- [x] `deny` 失败先审计再抛 -> `test_rag_context_audits_before_deny`
- [x] `degrade` 失败也审计 -> `test_rag_context_audits_on_degrade`
- [x] 审计不含查询与片段 -> `test_rag_audit_excludes_content`
- [x] 未配置审计时行为不变 -> `test_rag_context_without_audit_still_returns_block`
- [x] schema 含三个 rag 计数 -> `test_audit_schema_documents_rag_counts`
- [x] 全量门禁通过

## 反例

- [x] 基线 `AuditEvent` 不接受 `rag_top_k`（`extra="forbid"` 抛校验错误）
- [x] 基线 `RagContext` 没有 `audit` 参数，构造即 TypeError
- [x] 不区分过滤来源时计数会漏掉截断部分（用 3 条合格引用 + `top_k=1` 断言 filtered 至少含截断）

## 5 问威胁建模

1. **数据**：检索事件元数据（计数、状态、延迟），不含查询与片段。
2. **调用方**：运行 agent 的调用方与审计读者。
3. **信任边界**：检索结果 → 审计链；审计链是权威记录，不能写入语料内容。
4. **恶意输入最坏结果**：通过 `source_id` 或片段把语料或密钥带进审计链。缓解：事件只写计数与异常类型，
   `source_id` 与片段一律不进入审计字段。
5. **失败是否泄露信息**：`error_code` 只写异常类型名。

## 范围外

- 共享 `BudgetTracker` 接线（嵌入网关构造在入口接线切片）。
- 控制台展示检索事件（切片 4 视情况）。

## 证据

- `docs/evidence/SLICE-198-rag-retrieve-audit.txt`
