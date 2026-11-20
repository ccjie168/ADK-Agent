# SLICE-200 RAG 运维与使用手册

状态: gated
依据: ADR-0036（Accepted 2026-11-20）切片 5（收尾）。

## 意图

1. `docs/guides/operations.md` 的 RAG 一节补「运行时检索」：`--rag-*` 参数、只有 manifest 启用的
   agent 生效、`deny`/`degrade` 语义、`rag.retrieve` 审计字段、进程内预算、沙箱化触发跳过检索与
   MCP/A2A 未接线的现状。
2. `docs/guides/install-and-use.md` 增加「检索（RAG）」：写 manifest 的 `rag` 块、装语料（`rag ingest`
   单文件/目录）、自检（`rag search`）、在控制台开启、模型看到的上下文块形态与失败模式。
3. 两份手册的命令与参数必须与 `docs/contracts/cli.md` 一致。

## 契约（先改）

- 无代码与契约变更；文档引用既有契约。

## 完成判据

- [x] 运维手册含运行时检索配置与失败语义 -> `test_operations_guide_documents_rag_runtime`
- [x] 使用手册含 manifest 配置与装料流程 -> `test_install_guide_documents_rag_setup`
- [x] 两份手册都写到沙箱触发与 MCP/A2A 的现状 -> `test_guides_record_rag_wiring_gaps`
- [x] 手册里的参数与 CLI 契约一致 -> `test_guides_match_cli_contract`
- [x] 全量门禁通过

## 反例

- [x] 基线两份手册都不含 `rag` 配置示例与 `--rag-db`
- [x] 手册写 `--rag-db` 但契约没有该参数时，一致性用例应失败（用契约文本断言）

## 5 问威胁建模

1. **数据**：部署参数、manifest 配置示例与故障处理流程。
2. **调用方**：运维与发布人员。
3. **信任边界**：文档 → 部署行为。
4. **恶意输入最坏结果**：按文档把 `--data-class` 写成 `public` 覆盖机密语料，或让 `on_error=degrade`
   在生产静默降级。缓解：手册写明分级是调用方自述、必须有授权，`degrade` 是显式风险接受并在审计里可见。
5. **失败是否泄露信息**：示例只用占位 DSN 与假模型名。

## 范围外

- MCP/A2A 接线本身、沙箱触发接线、共享预算与模型网关联账（代码工作）。
- 真实环境演练（运维验收项）。

## 证据

- `docs/evidence/SLICE-200-rag-guides.txt`
