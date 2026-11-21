# SLICE-208 检索维度的入口校验

状态: gated
依据: PROGRESS 已知缺口第 9 条（`--rag-dimensions 0` 未捕获）。

## 意图

1. 服务命令（`console`、`serve`、`serve-many`、`serve-a2a`、`serve-triggers`）在
   `--rag-dimensions` 为 0 或负数时直接给出提示并退出 1，不再让 `RagStoreUnavailable` 以
   traceback 形式冒出。
2. `rag ingest`/`rag search` 与 `PgVectorRagStore` 的既有拒绝行为保持并加用例锁定。
3. 契约与运维手册写明维度必须是正整数。

## 契约（先改）

- `docs/contracts/cli.md` 的检索参数说明补「`--rag-dimensions` 必须是正整数；0 或负数退出 1」。

## 完成判据

- [x] 服务命令的工厂拒绝 0 与负数 -> `test_rag_factory_rejects_non_positive_dimensions`
- [x] 向量存储构造拒绝非正维度 -> `test_vector_store_rejects_non_positive_dimensions`
- [x] `rag ingest` 与 `rag search` 拒绝 0 维度 -> `test_rag_cli_rejects_zero_dimensions`
- [x] 全量门禁通过

## 反例

- [x] 基线 `ef81803`：服务命令的工厂不校验，`RagStoreUnavailable` 未被捕获，前两个用例失败。
- [x] 若只校验 0 不校验负数，负数用例失败。

## 5 问威胁建模

1. **数据**：检索维度配置。
2. **调用方**：运维的命令行与服务启动参数。
3. **信任边界**：部署配置 → 存储 schema。
4. **恶意输入最坏结果**：错误维度导致建表失败或半初始化状态；提示不清让运维误判。缓解：在入口
   校验并给出明确文案，进程不启动。
5. **失败是否泄露信息**：只输出参数名与要求，不含 DSN。

## 范围外

- 维度与既有表不匹配时的重建流程（已有运维手册说明）。

## 证据

- `docs/evidence/SLICE-208-rag-dimensions.txt`
