# SLICE-190 embedding 端口与 LiteLLM 实现 + 预算联动

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 2/6 / slice 2：embedding 走现有 LiteLLM 通道，不新增 provider；
embedding 成本计入 ADR-0033 的每租户预算。

## 意图

1. `core/model.py` 新增 `EmbeddingRequest`（`model`、`texts`）与 `EmbeddingResponse`
   （`vectors`、`model`、`input_tokens`、`cost_usd`、`egress`）。
2. `core/ports.py` 新增 `EmbeddingProvider` 协议（`name`、`egress`、`embed(request)`）。
3. `models/providers.py` 的 `LiteLlmProvider` 增加 `embed`：复用同一 `api_key`/`api_base` 走
   `litellm.aembedding`。
4. `models/embeddings.py` 新增 `EmbeddingGateway`：provider 允许清单检查、租户预算检查（超限
   `ModelDenied` 并审计 `budget_exceeded`）、成功后累计成本、每次调用审计 `model.embed`。
5. 类型从 `core` 导出。

## 契约（先改）

- 无对外 schema 变更（端口与网关实现）。

## 完成判据

- [ ] 网关返回 embedding 向量 -> `test_embedding_gateway_returns_vectors`
- [ ] 不在允许清单的 provider 被拒 -> `test_embedding_gateway_rejects_unlisted_provider`
- [ ] 超预算拒绝且不调用 provider -> `test_embedding_gateway_denies_over_budget`
- [ ] 成功后累计成本 -> `test_embedding_gateway_accumulates_cost`
- [ ] 每次调用写 `model.embed` 审计 -> `test_embedding_gateway_audits_call`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `adk_agent.models.embeddings` 不存在，`core` 无 `EmbeddingRequest`

## 5 问威胁建模

1. **数据**：待嵌入文本与向量、embedding 成本。
2. **调用方**：摄取管线与 `PgVectorRagService`（后续）。
3. **信任边界**：网关策略/预算到 provider 通道。
4. **恶意输入最坏结果**：绕过预算或把文本发往未批准通道（缓解：允许清单 + 预算检查在调用前，
   fail-closed）。
5. **失败是否泄露信息**：错误仅 `ModelDenied`/provider 异常，不泄露文本。

## 范围外

- `PgVectorRagService` 检索服务与摄取管线（后续）。
- 真实 LiteLLM embedding 调用的联网验证（本地无外网密钥，记入证据）。
- 运维手册更新（收尾切片）。

## 证据

- `docs/evidence/SLICE-190-embedding-port.txt`
