# SLICE-199 RAG 入口接线：控制台与触发

状态: gated
依据: ADR-0036（Accepted 2026-11-20）切片 4 的前半。

## 意图

1. 新增 `rag/factory.py` 的 `RagFactory`：一份共享存储与嵌入网关，按 manifest 的 `rag` 块给每个
   agent 构造 `RagContext`；未启用或没有 `rag` 块返回 `None`。
2. `build_rag_factory` 从部署配置（DSN、维度、模型、provider）构造生产实例，拒绝未知 provider。
3. `console` 与 `serve-triggers` 接受 `--rag-db`、`--rag-dimensions`、`--rag-model`、`--rag-provider`，
   未给 `--rag-db` 时完全不启用检索。
4. 控制台只在按需加载（有 manifest）时接线；`--agents` 文件加载的 agent 没有 manifest，不能开启检索。
   触发服务在每次执行时用 pinned 记录的 manifest 构造上下文。

## 契约（先改）

- `docs/contracts/cli.md`：两个命令的 `--rag-*` 参数、缺参退出 1、只对有 manifest 的 agent 生效。
- `docs/contracts/rag_service.md`：入口接线一节（共享存储、每 agent 一个上下文、文件加载的 agent 不启用）。

## 完成判据

- [x] 没有 `rag` 块或未启用时返回 `None` -> `test_factory_skips_manifests_without_rag`、`test_factory_skips_disabled_rag`
- [x] 启用时按 manifest 构造上下文 -> `test_factory_builds_context_from_manifest`
- [x] 同一 factory 共享存储 -> `test_factory_shares_one_store_across_contexts`
- [x] 未知 provider 被拒 -> `test_build_rag_factory_rejects_unknown_provider`
- [x] `--rag-db` 缺维度或模型退出 1 -> `test_cli_rag_factory_requires_dimensions_and_model`
- [x] 两个命令的 help 列出四个参数 -> `test_console_and_triggers_help_list_rag_flags`
- [x] 控制台按需加载把上下文传给 runtime -> `test_load_passes_rag_context_for_enabled_manifest`
- [x] 触发执行把上下文传给 runtime -> `test_fire_passes_rag_context_for_enabled_manifest`
- [x] 全量门禁通过

## 反例

- [x] 基线上没有 `adk_agent.rag.factory`，测试收集即 ImportError
- [x] 基线 `console --help` 不含 `--rag-db`
- [x] 不判断 `manifest.rag` 时，未启用的 agent 也会构造上下文（用未启用 manifest 断言 `None`）

## 5 问威胁建模

1. **数据**：共享 pgvector 存储与嵌入网关；每个 agent 的上下文绑定该 manifest 的 `top_k`、分级与
   `on_error`。
2. **调用方**：部署者（配置 DSN 与模型）与运行 agent 的调用方。
3. **信任边界**：部署配置 → 存储连接；manifest → 检索参数。
4. **恶意输入最坏结果**：把 `--rag-db` 指向他人库导致跨租户读取。缓解：检索按 principal 的租户走
   RLS，跨租户读取由数据库策略兜底；上下文不接收 agent 侧参数，全部来自 manifest。
5. **失败是否泄露信息**：构造失败只报参数缺失或未知 provider，不回显 DSN。

## 范围外

- MCP 与 A2A 入口（它们的 runner 与 runtime 形态不同，另行切片）。
- 共享 `BudgetTracker` 与模型网关的联账（当前只在嵌入网关内共享）。
- 运维与使用手册（切片 5）。

## 证据

- `docs/evidence/SLICE-199-rag-entry-wiring.txt`
