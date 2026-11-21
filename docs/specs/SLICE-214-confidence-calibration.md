# SLICE-214 置信度按余弦相似度截断

状态: gated
依据: PROGRESS 已知缺口第 9 条（置信度映射是线性启发式）；用户 2026-11-22 确认改判据。
批准: 用户选择「改成相似度截断」，明确同意修改 `tests/test_pgvector_rag_service.py` 的既有断言。

## 意图

1. `PgVectorRagService` 把余弦距离映射为置信度时改用余弦相似度：`confidence = clamp(1 - distance)`
   （即 `cos_sim` 截断到 `[0, 1]`）。当前 `1 - distance/2` 让正交（相似度 0）正好等于 0.5，
   默认 `min_confidence=0.5` 几乎不过滤。
2. 默认 `min_confidence=0.5` 因此等价于「余弦相似度 ≥ 0.5」；低于该值的分块在运行时预取里被丢弃。
3. 契约写明映射与默认门槛的含义。

## 契约（先改）

- `docs/contracts/rag_service.md` 的 `Citation.confidence` 条目：置信度是截断后的余弦相似度，
  `min_confidence` 与之比较；默认 0.5 即相似度门槛 0.5。
- 运维或使用手册的检索一节同步一句。

## 完成判据

- [x] 映射改用相似度截断 -> `test_retrieve_maps_distance_to_confidence`（改既有断言，已获批准）
- [x] 默认门槛丢弃正交分块 -> `test_retrieve_default_guard_drops_orthogonal_chunks`
- [x] 边界保持单调与截断 -> `test_confidence_is_clamped`
- [x] 全量门禁通过

## 反例

- 基线 `8594c00`：`test_retrieve_maps_distance_to_confidence` 期望 `[1.0, 0.5, 0.0]`，新期望
  `[1.0, 0.0, 0.0]` 失败；`test_retrieve_default_guard_drops_orthogonal_chunks` 里距离 1.0 的分块
  仍被保留，失败。
- 若只截断下界不做上界，`test_confidence_is_clamped` 失败。

## 5 问威胁建模

1. **数据**：检索返回的分块与其置信度。
2. **调用方**：运行时预取（`RagContext`）与直接使用 `PgVectorRagService` 的代码。
3. **信任边界**：向量库距离 → 注入提示的上下文。
4. **恶意输入最坏结果**：不相关分块因阈值失效进入提示，扩大提示注入与噪音面。缓解：置信度等于
   相似度，默认门槛真正删除不相关分块。
5. **失败是否泄露信息**：只影响过滤，不新增输出字段。

## 范围外

- 重排（rerank）与按来源去重。
- 真实 embedding 下的阈值调参（需要验收数据）。
- `InMemoryRagService` 的置信度语义不变。

## 证据

- `docs/evidence/SLICE-214-confidence-calibration.txt`
