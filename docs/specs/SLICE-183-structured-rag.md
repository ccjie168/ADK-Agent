# SLICE-183 结构化检索实现 + ACL 过滤

状态: gated
依据: ADR-0032（Accepted 2026-11-19）决定 3 / slice 2：第一段结构化数据检索 + 引用；检索必须按调用方
权限过滤（ACL 契约）。

## 意图

1. `src/adk_agent/rag/memory.py` 新增 `RagSource`（`source_id`/`snippet`/`data_classes`/
   `allowed_tenants`/`allowed_subjects`）。
2. 同文件新增 `InMemoryRagService` 实现 `RagService`：按 ACL、`data_classes` 与查询子串匹配过滤，
   返回 `acl_checked=True` 的 `Citation`。
3. 从 `adk_agent.rag` 导出 `RagSource`/`InMemoryRagService`。

## 契约（先改）

- 无对外 schema 变更（实现，端口契约已在 SLICE-182）。

## 完成判据

- [ ] ACL 可见来源返回 -> `test_retrieve_returns_acl_visible_source`
- [ ] 无权限租户不返回 -> `test_retrieve_hides_unauthorized_tenant`
- [ ] 无权限 subject 不返回 -> `test_retrieve_hides_unauthorized_subject`
- [ ] data_classes 过滤 -> `test_retrieve_filters_by_data_classes`
- [ ] 查询匹配 -> `test_retrieve_matches_query`
- [ ] 返回引用均 acl_checked -> `test_retrieved_citations_are_acl_checked`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `RagSource`/`InMemoryRagService`

## 5 问威胁建模

1. **数据**：结构化检索来源及其 ACL/data_classes 元数据。
2. **调用方**：模型上下文组装（未来）。
3. **信任边界**：检索服务到调用方（越权来源泄漏是边界风险）。
4. **恶意输入最坏结果**：无权来源被返回进上下文（缓解：ACL + data_classes 过滤，`acl_checked` 置真）。
5. **失败是否泄露信息**：无新错误面。

## 范围外

- 提示注入防护 + 低置信度拒答（slice 3）。
- 真实 SQL/API 后端（后续）。
- 向量后端独立 ADR。

## 证据

- `docs/evidence/SLICE-183-structured-rag.txt`
