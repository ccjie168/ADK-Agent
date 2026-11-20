# ADR-0035 向量后端与 embedding 选型

状态: Proposed   日期: 2026-11-20   起草: Claude Code   待签字

## 背景

ADR-0032 定下 `RagService` 端口与 ACL 契约，并明确「向量库与 embedding 的选型在端口验证后单独 ADR」。
SLICE-182 到 SLICE-184 已交付端口、`Citation`、内存结构化检索与注入/低置信度守卫。第二段非结构化 RAG
（解析、分块、embedding、索引、重排）仍缺后端，FR-008 因此停在 AMBER。

约束来自既有决定：

- 不新增依赖、不新增模型通道，除非 ADR 明确接受（CLAUDE.md 硬规则）。
- 多副本部署已由 Postgres 承担共享状态（配额、审计、审批、注册表），运维手册已覆盖备份与恢复。
- 检索结果必须带 ACL 过滤与引用（ADR-0032），预算必须可执行（ADR-0033）。

## 决定（草案）

1. **向量存储选 Postgres + `pgvector` 扩展。** 不引入独立向量数据库服务。新表
   `adk_rag_chunks(tenant, source_id, chunk_id, text, embedding vector(N), data_classes text[],
   acl jsonb, updated_at)`，主键 `(tenant, source_id, chunk_id)`，按租户启用 RLS（与配额、会话同一模式）。
2. **embedding 走现有 LiteLLM 通道。** `ModelProvider` 增加可选 `embed(texts) -> list[list[float]]`，
   LiteLLM 实现复用同一 base URL 与密钥来源；维度 `N` 在部署配置中固定并写入表定义。
   不新增 provider，不新增 Python 依赖。
3. **检索沿用 ADR-0032 契约。** `PgVectorRagService` 实现 `RagService`：先按 `principal` 与
   `data_classes` 过滤（SQL 条件 + ACL 元数据），再做近邻排序，返回带 `acl_checked=True` 的 `Citation`；
   低置信度与注入守卫复用 SLICE-184 的 `RagGuard`。
4. **摄取最小化。** 结构化来源（连接器/SQL）→ 分块 → `embed` → upsert；ACL 元数据在摄取时与来源绑定，
   与 ADR-0032 契约一致。无独立摄取服务，先由 CLI 触发。
5. **失败语义。** 扩展缺失、维度不符或 embedding 调用失败时 fail-closed：检索返回空并记录明确错误，
   不降级到无 ACL 过滤的路径。
6. **预算联动。** embedding 调用计入 ADR-0033 的租户预算（同一 `BudgetTracker`），超限停止。

## 备选与否决

- **Qdrant / Weaviate / Milvus**：独立服务，新增部署单元、备份与密钥面，MVP 不划算；否决。
- **Chroma 嵌入式**：引入另一套本地存储与依赖，跨副本共享需要重做；否决。
- **纯内存向量索引**：无持久化、无法多副本，重启即失效；否决。
- **sentence-transformers 本地 embedding**：重依赖与 GPU 要求，超出当前运行时；否决。
- **只做结构化检索不做向量**：FR-008 无法收口；否决。

## 后果

- Postgres 需启用 `pgvector` 扩展；运维手册与多副本清单要补扩展安装、维度变更与重建索引步骤。
- `ModelProvider` 增加可选 `embed`，LiteLLM 实现补齐；未提供 `embed` 的 provider 在摄取与向量检索时
  fail-closed。
- embedding 调用产生成本，与 ADR-0033 预算共用计数。
- 维度固定为部署配置；换模型需重建索引，写进运维手册。

## 待确认问题

1. 是否接受 Postgres + `pgvector` 作为向量存储（而不是独立向量库）。
2. embedding 是否复用 LiteLLM 通道（接受其成本与数据出站，按 ADR-0021 的 egress 审计）。
3. 默认 embedding 模型与维度是否由部署配置决定，MVP 不内置默认值。

## 切片（确认后分配）

1. `pgvector` 表、扩展安装与 RLS 迁移脚本。
2. `ModelProvider.embed` + LiteLLM 实现 + 预算联动。
3. 摄取管线（分块、embed、upsert，CLI 触发）。
4. `PgVectorRagService` 检索实现 + ACL/注入/低置信度测试。
5. 运维手册与多副本清单更新。
