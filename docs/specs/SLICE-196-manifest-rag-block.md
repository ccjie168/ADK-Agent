# SLICE-196 manifest 的 rag 配置块

状态: gated
依据: ADR-0036（Accepted 2026-11-20）决定 1 与切片 1。

## 意图

1. `AgentManifest` 新增可选 `rag` 块，字段与缺省值按 ADR-0036：`enabled`（默认 `false`）、
   `top_k`（默认 5，1..50）、`min_confidence`（默认 0.5，0..1）、`data_classes`（默认空列表）、
   `on_error`（`deny`|`degrade`，默认 `deny`）。
2. 存量 manifest 的 digest 不变：`rag` 为 `None` 时从摘要载荷剔除；显式给出的 `rag` 参与摘要。
3. 重生成 `manifest.schema.json`，并在 `docs/contracts/rag_service.md` 记录该块。

## 契约（先改）

- `docs/contracts/rag_service.md` 增加「manifest 配置（ADR-0036）」一节：字段、缺省值、取值范围、
  digest 语义。
- `docs/contracts/manifest.schema.json` 由 `scripts/export_contracts.py` 重生成。

## 完成判据

- [x] 缺省值与 ADR 一致 -> `test_manifest_rag_defaults`
- [x] `top_k` 越界被拒 -> `test_manifest_rag_rejects_bad_top_k`
- [x] `on_error` 非法取值被拒 -> `test_manifest_rag_rejects_bad_on_error`
- [x] `min_confidence` 越界被拒 -> `test_manifest_rag_rejects_bad_confidence`
- [x] 不带 `rag` 的存量 manifest digest 不变 -> `test_legacy_manifest_digest_ignores_missing_rag`
- [x] 带 `rag` 的 manifest digest 变化 -> `test_manifest_digest_changes_with_rag`
- [x] schema 含 `rag` 定义 -> `test_manifest_schema_documents_rag`
- [x] 全量门禁通过

## 反例

- [x] 基线 `AgentManifest` 没有 `rag` 字段，构造时传 `rag` 抛校验错误
- [x] 基线 `manifest.schema.json` 不含 `RagConfig`
- [x] 若直接把 `rag=None` 留进摘要载荷，存量记录的 digest 全部变化

## 5 问威胁建模

1. **数据**：manifest 里的检索配置；digest 绑定发布内容。
2. **调用方**：发布者，以及读取 manifest 的运行路径。
3. **信任边界**：manifest → 运行时行为；digest → 验签与固定引用。
4. **恶意输入最坏结果**：用超大 `top_k` 放大上下文与成本，或用 `min_confidence=0` 关掉过滤后注入
   对抗性片段。缓解：`top_k` 上限 50 由模型校验；`min_confidence` 限定 0..1；`RagGuard` 的注入模式
   检测不受配置影响（切片 2 落地）。
5. **失败是否泄露信息**：digest 是本机计算，不泄露配置内容。

## 范围外

- 运行时预取与注入（切片 2）。
- 审计与预算（切片 3）。
- 控制台展示与文档手册（切片 4）。

## 证据

- `docs/evidence/SLICE-196-manifest-rag-block.txt`
