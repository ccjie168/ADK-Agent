# SLICE-192 PgVectorRagService 检索服务

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 3 / slice 4：`PgVectorRagService` 实现 ADR-0032 的
`RagService`，先 ACL 过滤再近邻排序，返回 `acl_checked=True` 的引用，可接 `RagGuard`。

## 意图

1. `rag/vector_store.py` 的 `RagChunkRow` 增加 `distance: float = 0.0`，`search` 返回余弦距离。
2. `rag/pgvector_service.py` 新增 `PgVectorRagService(store, embedder, *, provider, model, guard=None, limit=10)`：
   `retrieve(query, principal, data_classes, *, invocation=None, policy=None)` 先嵌入查询（缺 invocation/policy 抛
   `ValueError`），再按租户/subject/data_classes 搜索，把距离映射为置信度（`1 - distance/2`，夹在 0..1），
   生成 `acl_checked=True` 的 `Citation`，最后应用 `RagGuard`。
3. 从 `adk_agent.rag` 导出 `PgVectorRagService`。

## 契约（先改）

- 无对外 schema 变更。

## 完成判据

- [ ] 检索嵌入查询并按 ACL 参数搜索 -> `test_retrieve_embeds_and_searches`
- [ ] 距离映射为置信度 -> `test_retrieve_maps_distance_to_confidence`
- [ ] 守卫过滤低置信度 -> `test_retrieve_applies_guard`
- [ ] 缺 invocation 或 policy 拒绝 -> `test_retrieve_requires_invocation_and_policy`
- [ ] 无结果返回空列表 -> `test_retrieve_empty`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `adk_agent.rag.pgvector_service`

## 5 问威胁建模

1. **数据**：查询文本、检索结果、置信度。
2. **调用方**：模型上下文组装（后续）。
3. **信任边界**：查询到存储；跨租户读取是核心风险。
4. **恶意输入最坏结果**：跨租户或无 ACL 过滤的结果进入上下文（缓解：tenant 取自 principal，存储层
   双重过滤，`acl_checked` 恒真）。
5. **失败是否泄露信息**：失败仅报 `RagStoreUnavailable` 或 embedding 异常，不返回部分结果。

## 范围外

- 重排模型与引用拼接（后续）。
- CLI 与运维手册（收尾切片）。

## 证据

- `docs/evidence/SLICE-192-pgvector-rag-service.txt`
