# SLICE-182 RagService 端口与 Citation 类型 + ACL 契约

状态: gated
依据: ADR-0032（Accepted 2026-11-19）决定 1/2 / slice 1：先定义 `RagService` 端口与 ACL 契约，再选
向量库。本切片只落端口、类型与契约文档。

## 意图

1. `src/adk_agent/rag/` 新增 `Citation` 类型：`source_id`、`snippet`、`acl_checked: bool`、`confidence: float`（0..1）。
2. 同包新增 `RagService` 协议：`async retrieve(query, principal, data_classes) -> list[Citation]`。
3. `docs/contracts/rag_service.md` 记录 ACL 契约：检索必须按调用方权限过滤，`acl_checked=True` 表示已过滤，
   绝不返回无权来源；ACL 元数据在摄取时绑定。

## 契约（先改）

- `docs/contracts/rag_service.md`（新增）：端口签名与 ACL 契约。

## 完成判据

- [ ] Citation 字段可构造 -> `test_citation_fields`
- [ ] confidence 越界拒绝 -> `test_citation_confidence_bounds`
- [ ] source_id/snippet 非空 -> `test_citation_requires_source_and_snippet`
- [ ] RagService 可 import -> `test_rag_service_importable`
- [ ] ACL 契约文档存在且含过滤不变式 -> `test_rag_acl_contract_doc`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `adk_agent.rag`、无 `Citation`/`RagService`、无 `docs/contracts/rag_service.md`

## 5 问威胁建模

1. **数据**：检索引用及其 ACL 过滤标记。
2. **调用方**：未来结构化检索与向量 RAG 实现、模型上下文组装。
3. **信任边界**：检索服务到调用方（越权来源泄漏是边界风险）。
4. **恶意输入最坏结果**：无权来源被返回进上下文（缓解：`acl_checked` 标记 + 契约要求过滤）。
5. **失败是否泄露信息**：仅类型与文档，无新错误面。

## 范围外

- 结构化检索实现 + ACL 过滤测试（slice 2）。
- 提示注入防护 + 低置信度拒答（slice 3）。
- 向量后端独立 ADR（slice 4/后续）。

## 证据

- `docs/evidence/SLICE-182-rag-service-port.txt`
