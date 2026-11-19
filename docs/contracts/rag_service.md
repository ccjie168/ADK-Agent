# RagService 端口与 ACL 契约

依据：ADR-0032。

## 端口

`RagService.retrieve(query, principal, data_classes) -> list[Citation]`，异步。实现方在
`src/adk_agent/rag/` 之外，端口先定，向量库/embedding 选型另行 ADR。

`Citation`：

- `source_id`（非空）：来源标识。
- `snippet`（非空）：检索片段。
- `acl_checked`（bool）：`True` 表示已按调用方权限过滤。
- `confidence`（0..1）：置信度。

## ACL 契约

- 检索必须按调用方权限过滤，绝不返回调用方无权访问的来源。
- `acl_checked=True` 是「已按 `principal` 权限过滤」的标记；检索结果交给调用方前必须置真。
- ACL 元数据在摄取时绑定到来源，检索时按 `principal` 判定。
- 同步延迟作为契约字段（权威源 + 容忍值），默认 SharePoint 为权威，容忍值待 Owner 确认。
