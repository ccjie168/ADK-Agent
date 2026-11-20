# SLICE-193 RAG 运维文档与多副本说明

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 / slice 5：运维手册与多副本清单要补 pgvector 扩展安装、
维度变更与重建索引步骤。

## 意图

1. `docs/guides/operations.md` 增加「RAG 向量存储（pgvector）」一节：扩展安装、表与 RLS 由首个连接
   自建、维度配置与换模型重建索引、多副本共享同一库。
2. 同节写明失败模式：扩展缺失或维度不符时检索 fail-closed（空结果 + `RagStoreUnavailable`），
   不降级到无 ACL 路径。

## 契约（先改）

- 无代码变更（纯文档）。

## 完成判据

- [x] 运维手册含 pgvector 安装步骤 -> `test_operations_guide_covers_pgvector_install`
- [x] 含维度与重建索引说明 -> `test_operations_guide_covers_dimensions`
- [x] 含 fail-closed 失败模式 -> `test_operations_guide_covers_rag_failure_modes`
- [x] 含多副本共享说明 -> `test_operations_guide_covers_multi_replica`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `operations.md` 未提及 pgvector

## 5 问威胁建模

1. **数据**：向量库的部署与运维说明。
2. **调用方**：运维与发布人员。
3. **信任边界**：文档到部署行为。
4. **恶意输入最坏结果**：运维按文档跳过 RLS 或扩展校验导致越权（缓解：文档写明强制项与 fail-closed）。
5. **失败是否泄露信息**：无。

## 范围外

- CLI 接线（后续）。
- 真实环境安装演练（运维验收项）。

## 证据

- `docs/evidence/SLICE-193-rag-ops-docs.txt`
