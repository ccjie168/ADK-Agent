# SLICE-191 RAG 摄取管线

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 4 / slice 3：结构化来源 → 分块 → embed → upsert，ACL 元数据
摄取时绑定；无独立摄取服务，先由库调用触发。

## 意图

1. `rag/ingest.py` 新增 `split_text(text, *, max_chars)`：按段落/空白切分，块长不超过 `max_chars`，
   拼接后可还原全部非空白内容。
2. 新增 `IngestionPipeline(store, embedder, *, provider, model)`：`ingest(invocation, tenant, source_id,
   text, data_classes, allowed_subjects, policy)` 分块 → `EmbeddingGateway.embed` → 组装 `RagChunk` →
   `store.upsert`，返回写入块数。
3. 空文本或空分块结果抛 `ValueError`；embedding 失败向上传播且不写存储（fail-closed）。

## 契约（先改）

- 无对外 schema 变更（库内管线）。

## 完成判据

- [ ] 分块不超长且可还原 -> `test_split_text_respects_max_chars`
- [ ] 管线写入带 ACL 的分块 -> `test_ingest_writes_chunks_with_acl`
- [ ] 空文本拒绝 -> `test_ingest_rejects_empty_text`
- [ ] embedding 失败不写存储 -> `test_ingest_propagates_embedding_failure`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `adk_agent.rag.ingest`

## 5 问威胁建模

1. **数据**：待入库文本、分块、ACL 元数据。
2. **调用方**：库调用（CLI 接线后置）。
3. **信任边界**：输入文本到向量存储。
4. **恶意输入最坏结果**：ACL 缺失导致越权可见（缓解：管线强制带 `data_classes`，subject 可选但显式传参）。
5. **失败是否泄露信息**：不吞异常、不部分写入。

## 范围外

- CLI 命令接线（后续）。
- 重排、引用拼接、`PgVectorRagService` 检索服务（下一刀）。
- 运维手册更新（收尾切片）。

## 证据

- `docs/evidence/SLICE-191-rag-ingest.txt`
