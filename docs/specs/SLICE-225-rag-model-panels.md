# SLICE-225 RAG 面板 + 模型网关面板

状态: gated
依据: ADR-0039 MVP 第 4 项（构建能力补全：RAG 面板 + 模型网关面板，只读查询可视化）

## 意图

1. 新增 `GET /api/rag`：从最近审计事件里统计 `rag.retrieve` 的条数与最近一次检索的
   `rag_top_k` / `rag_returned`，作为 RAG 面板的只读概览。
2. 新增 `GET /api/model`：从最近审计事件里统计 `model.call` 的条数、用到的别名集合与
   `fallback_count` 总和，作为模型网关面板的只读概览。
3. 新增 RAG 面板 `section#rag` 与模型网关面板 `section#model`，用 `.stat-card` 展示计数，
   导航「构建」组加 RAG / Model tab。

## 契约（先改）

- `docs/contracts/console.md` 补 `GET /api/rag` 与 `GET /api/model` 两节。
- 两个端点返回的都是「最近审计窗口」的计数摘要，不是全局计数器，契约里写明窗口语义。

## 完成判据

- [x] 首页含 RAG 与模型面板 -> `test_index_has_rag_and_model_panels`
- [x] RAG 端点返回检索统计 -> `test_rag_endpoint_returns_stats`
- [x] 模型端点返回调用统计 -> `test_model_endpoint_returns_stats`
- [x] 全量门禁通过

## 反例

- 基线 `f58ec0e`：首页没有 `id="rag"` / `id="model"`，没有 `/api/rag` / `/api/model` 路由，
  三个用例分别失败（404）。

## 5 问威胁建模

1. **数据**：最近审计事件里的 `rag.retrieve` / `model.call` 计数与摘要字段。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 租户 → 可见的审计摘要。
4. **恶意输入最坏结果**：越权读其它租户的检索/调用摘要。缓解：复用 `_query_events` 的租户过滤，
   非 admin 只看到自己租户的事件；只返回计数与有限字段，不含消息正文。
5. **失败是否泄露信息**：审计不可用返回 502 `audit_unavailable`，不泄露后端状态。

## 范围外

- RAG 语料/分块数的存储级统计（需要 `PgVectorRagStore` 计数方法，另开切片）。
- 模型网关的实时熔断/预算余额（在独立 `serve-model-gateway` 进程里，console 不直连）。
- 语义层面板（SLICE-226）。

## 证据

- `docs/evidence/SLICE-225-rag-model-panels.txt`
