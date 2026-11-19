# ADR-0032 RagService 端口与 ACL 契约

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

全库无 RAG（无 vector/embedding/retrieval/citation），FR-008 为 RED；MVP-1 需要检索 + 引用。
风险是「一上来选向量库」，把产品选型当成架构。应先定义 `RagService` 端口与 ACL 契约，再选厂商。

## 决定

1. **先定义 `RagService` 端口**（`src/adk_agent/rag/`）：
   `retrieve(query, principal, data_classes) -> list[Citation]`。`Citation` 携带
   `source_id`、`snippet`、`acl_checked`（已按调用方权限过滤）、`confidence`。
2. **ACL 契约。** 检索必须按调用方权限过滤，绝不返回调用方无权访问的来源；ACL 元数据在摄取时
   绑定。这是端口契约，不是实现细节。
3. **两段实现。** 第一段结构化数据检索 + 引用（SQL/API over DSS/CDP/SAP 异常），第二段非结构化
   RAG（解析/分块/embedding/索引/重排）。向量库与 embedding 的选型在端口验证后再开单独 ADR。
4. **提示注入防护与低置信度拒答是端口契约的一部分**，不是事后补丁：检索内容进上下文前做
   注入检测，无来源或低置信度不得生成确定性业务结论。
5. **ACL 同步延迟作为契约字段**（权威源 + 容忍值），默认 SharePoint 为权威，容忍值待 Owner
   确认（非本 ADR 拍板）。

## 备选与否决

- **直接选向量库实现**：架构 ≠ 选型，端口未定就绑定厂商会返工；否决。
- **RAG 作为工具而非服务**：检索需要权限过滤与引用，属于平台能力而非普通工具；否决。

## 后果

- 新增 `src/adk_agent/rag/` 模块与契约（`docs/contracts/rag_*.md`）。
- 向量库/embedding 是独立 ADR（新依赖需 ADR），不并入本 ADR。
- 第一段结构化检索可用现有连接器实现，先给 GSC 场景交付引用能力。

## 切片（待确认后分配）

1. 端口 + `Citation` 类型 + ACL 契约（先红后绿）。
2. 结构化检索实现 + ACL 过滤测试。
3. 提示注入防护 + 低置信度拒答。
4. （后续）向量后端独立 ADR。
