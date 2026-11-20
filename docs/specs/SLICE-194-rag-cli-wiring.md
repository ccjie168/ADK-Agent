# SLICE-194 RAG 摄取与检索的 CLI 接线

状态: gated
依据: ADR-0035（Accepted 2026-11-20）决定 3（模型与维度由部署配置决定）与 slice 5 的已知缺口
（`PgVectorRagStore` 只由部署代码构造，`serve-*` 与 CLI 未接线）。

## 意图

1. 新增 `adk-agent rag ingest`：读入一份文本，走既有 `IngestionPipeline`（分块 → 经 `EmbeddingGateway`
   嵌入并记 `model.embed` 审计 → 带 ACL 写入 `adk_rag_chunks`），供运维在不写代码的情况下装载语料。
2. 新增 `adk-agent rag search`：走既有 `PgVectorRagService`（嵌入查询、按 principal 的 ACL 检索、
   距离转置信度、`RagGuard` 过滤），输出引用 JSON，用于装载后自检。
3. 两者只做接线，不新增检索或写入语义；维度与模型由命令行显式给出，不做隐式发现。

## 契约（先改）

- `docs/contracts/cli.md` 增加 `rag ingest` 与 `rag search` 两节：参数、退出码、输出形状、
  审计后端沿用 `--audit-file|--audit-url|--audit-db`、维度不符与存储不可用的失败语义。

## 完成判据

- [x] `rag ingest` 把分块写入存储 -> `test_rag_ingest_writes_chunks`
- [x] `rag ingest` 空文本退出 1 且不写存储 -> `test_rag_ingest_rejects_empty_text`
- [x] `rag ingest` 存储不可用退出 1 -> `test_rag_ingest_reports_store_unavailable`
- [x] `rag ingest` 每次嵌入写 `model.embed` 审计 -> `test_rag_ingest_audits_embedding`
- [x] `rag ingest` 正文文件读不到时退出 1 且无栈回溯 -> `test_rag_ingest_reports_missing_text_file`
- [x] `rag search` 输出带 ACL 标记与置信度的引用 -> `test_rag_search_returns_citations`
- [x] `rag search` 过滤低于阈值的引用 -> `test_rag_search_drops_low_confidence`
- [x] `rag search` 拒绝非正的 `--limit` -> `test_rag_search_rejects_non_positive_limit`
- [x] `rag --help` 列出两段命令与关键参数 -> `test_rag_help_lists_rag_flags`
- [x] 契约 `cli.md` 记录两段命令 -> `test_cli_contract_documents_rag_commands`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `adk-agent rag --help` 退出 2（未知子命令）
- [x] 基线上 `docs/contracts/cli.md` 不含 `rag ingest`
- [x] 空文本不产生任何 `upsert` 调用（用假 store 断言调用次数为 0）
- [x] 存储抛 `RagStoreUnavailable` 时进程退出 1，且不输出成功 JSON

## 5 问威胁建模

1. **数据**：语料正文与向量，写入 `adk_rag_chunks`；命令行传入的租户、数据分级与可见主体。
2. **调用方**：持有数据库 DSN 与模型通道凭据的运维人员或批处理作业。
3. **信任边界**：命令行参数 → 存储的租户与 ACL 列；嵌入调用 → 第三方模型通道。
4. **恶意输入最坏结果**：把 `confidential` 语料标成 `public`，或把 `--subject` 省略后写入租户内全员可见的
   分块，造成越权检索。缓解：默认不写 `allowed_subjects`（即租户内可见）要在契约里写明；`--data-class`
   缺省为空列表时检索侧要求调用方声明数据分级才会命中，等于默认不可见；输出不含 DSN 与凭据。
5. **失败是否泄露信息**：错误只打印异常类型与安全文案，不回显 DSN、正文或向量。

## 范围外

- `serve-*` 的 RAG 接线（agent 运行路径还没有调用 `RagService` 的代码）。
- 重排、引用拼接、置信度校准。
- 批量目录摄取与删除来源。
- 真实环境验证（需要 `TEST_POSTGRES_URL`、pgvector 与模型通道凭据，属运维验收项）。

## 证据

- `docs/evidence/SLICE-194-rag-cli-wiring.txt`
