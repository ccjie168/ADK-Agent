# SLICE-211 重新摄取整源替换

状态: gated
依据: PROGRESS 已知缺口第 9 条（目录摄取不做增量同步，文件变短会留下尾部分块）。

## 意图

1. `IngestionPipeline` 写入时走 `ChunkStore.replace`：同一 `(tenant, source_id)` 的新分块集合在同一个
   事务里删除该来源不再存在的分块，再写入新分块。文件变短、分块边界变化都不会留下陈旧内容。
2. 其他来源的行不受影响；替换是原子的，读方看不到中间状态。
3. 切分后没有内容仍然在写入前拒绝，已有分块保持不动。

## 契约（先改）

- `docs/contracts/rag_service.md` 新增「摄取与替换」一节。
- `docs/contracts/cli.md` 的 `rag ingest` 一节把「按主键覆盖」改为整源替换。

## 完成判据

- [x] 重新摄取只保留新分块 -> `test_reingest_replaces_stale_chunks`
- [x] 其他来源不受影响 -> `test_reingest_leaves_other_sources_alone`
- [x] 向量存储的事务替换 -> `test_replace_removes_stale_chunks`（live，需 `TEST_POSTGRES_URL`）
- [x] 全量门禁通过

## 反例

- 基线 `34c088f`：`IngestionPipeline` 调 `store.upsert`，假存储实现 `replace`，三个新用例全部
  `AttributeError` 失败；文件变短时旧分块保留。
- 若替换不按 `source_id` 过滤，`test_reingest_leaves_other_sources_alone` 失败。

## 5 问威胁建模

1. **数据**：租户内的检索分块。
2. **调用方**：运维的 `rag ingest`（单文件与目录）。
3. **信任边界**：来源文件 → 存储行。
4. **恶意输入最坏结果**：陈旧分块继续被检索，模型拿到已删除的内容；或误删其他来源的数据。
   缓解：删除条件限定同一租户与同一 `source_id`，与插入同事务。
5. **失败是否泄露信息**：失败只给异常类型，不含 DSN 或正文。

## 范围外

- 目录级增量同步（按 mtime/摘要跳过未变文件）。
- `is_symlink` 与 `read_text` 之间的 TOCTOU 窗口。
- 删除已停用来源的显式清理命令。

## 证据

- `docs/evidence/SLICE-211-rag-replace-source.txt`
