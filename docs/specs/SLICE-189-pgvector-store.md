# SLICE-189 pgvector 向量存储与 RLS

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 1 / ADR-0032 slice 4 第一段：Postgres + `pgvector`
新表 `adk_rag_chunks`，按租户 RLS，接收集成前的向量写入与近邻检索。

## 意图

1. `rag/vector_store.py` 新增 `RagChunk`（`tenant`/`source_id`/`chunk_id`/`text`/`embedding`/
   `data_classes`/`allowed_subjects`）与 `PgVectorRagStore`。
2. 构造时校验 `dimensions`，并建立 `CREATE EXTENSION IF NOT EXISTS vector` 与
   `adk_rag_chunks`（主键 `(tenant, source_id, chunk_id)`，`embedding vector(N)`，`acl jsonb`）。
3. `upsert` 写入或覆盖分块；`search` 按租户、`data_classes` 交集与 `allowed_subjects` 过滤后按余弦距离
   排序并限量返回。
4. RLS：`ENABLE`/`FORCE ROW LEVEL SECURITY`，策略为 `tenant = current_setting('app.tenant_id', true)`；
   每次查询在事务内设置 `app.tenant_id`。
5. 扩展不可用或维度不符时抛 `RagStoreUnavailable`，不静默降级。

## 契约（先改）

- 无对外 schema 变更（存储实现）。

## 完成判据

- [ ] 维度与分块校验 -> `test_rag_chunk_validates_embedding_dimensions`
- [ ] upsert 后可按近邻取回（需 `TEST_POSTGRES_URL`） -> `test_upsert_and_search_roundtrip`
- [ ] data_classes 过滤 -> `test_search_filters_by_data_classes`
- [ ] allowed_subjects 过滤 -> `test_search_filters_by_subject`
- [ ] 租户隔离 -> `test_search_is_tenant_scoped`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `adk_agent.rag.vector_store`

## 5 问威胁建模

1. **数据**：分块文本、向量、ACL 元数据。
2. **调用方**：摄取管线（后续）、`PgVectorRagService`（后续）。
3. **信任边界**：存储层租户与 ACL 过滤。
4. **恶意输入最坏结果**：跨租户读到分块（缓解：RLS + 查询显式租户条件双保险）。
5. **失败是否泄露信息**：错误仅报不可用，不带分块内容。

## 范围外

- `ModelProvider.embed` 与 LiteLLM 实现（下一刀）。
- 摄取管线与 `PgVectorRagService`（后续）。
- 运维手册更新（收尾切片）。

## 证据

- `docs/evidence/SLICE-189-pgvector-store.txt`
