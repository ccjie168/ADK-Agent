# SLICE-173 工具幂等存储（文件 + Postgres）

状态: gated
依据: ADR-0034（Accepted 2026-11-19）决定 3 / slice 2（后半）：网关维护
`idempotency_key → execution record → result` 映射，记录带 TTL 与 `(tenant, tool_id, idempotency_key)`
唯一约束，复用触发执行的文件 + Postgres 双实现模式。本切片只落地存储与记录类型，网关接线（重复 key
重放 + 序列化失败语义）后置到 slice 4。

## 意图

1. `core/tool_idempotency.py` 新增 `ToolExecutionRecord`：`(tenant, tool_id, idempotency_key)` 唯一，
   状态 `claimed`/`completed`/`unknown`，带 `output`/`data_classes`/`error_code` 与 TTL（`expires_at`），
   时间戳必须 timezone-aware，终态需要 `finished_at`、`claimed` 不得有 `finished_at`。
2. `core/ports.py` 新增 `ToolIdempotencyStore` 协议（`claim`/`finish`/`get`/`aclose`）。
3. `tools/idempotency.py` 新增 `FileToolIdempotencyStore`：`<root>/<tenant>/<tool_id>/<sha256(key)>.json`，
   `os.link` 单赢家，`safe_join` 校验路径段。
4. `tools/idempotency_postgres.py` 新增 `PostgresToolIdempotencyStore`：`adk_tool_idempotency` 表，
   `(tenant, tool_id, idempotency_key)` 主键，`ON CONFLICT DO NOTHING` 单赢家。
5. 类型从 `core` 与 `tools` 导出。

## 契约（先改）

- 无对外 schema 变更（存储为内部实现，不进入 `export_contracts.py`）。

## 完成判据

- [ ] 首次 claim 返回新记录 -> `test_claim_has_a_single_winner`
- [ ] 重复 claim 返回已存在记录 -> `test_claim_returns_existing`
- [ ] finish 更新为终态 -> `test_finish_updates_the_record`
- [ ] finish 未知 key 抛冲突 -> `test_finish_unknown_key_is_a_conflict`
- [ ] 终态/claimed 的 finished_at 约束 -> `test_record_terminal_state_constraints`
- [ ] 文件存储拒绝不安全路径 -> `test_file_store_unsafe_paths_are_rejected`
- [ ] Postgres 单赢家与重放（有 `TEST_POSTGRES_URL` 时） -> `test_postgres_claim_has_a_single_winner`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `ToolExecutionRecord`/`FileToolIdempotencyStore`/`PostgresToolIdempotencyStore`

## 5 问威胁建模

1. **数据**：写工具执行记录（结果、状态、TTL）。
2. **调用方**：工具网关（slice 4 接线）、控制台/执行器。
3. **信任边界**：`idempotency_key`（调用方可控，哈希后落盘）→ 存储路径。
4. **恶意输入最坏结果**：路径穿越或重复执行（缓解：`safe_join` + `sha256(key)` + `os.link`/`ON CONFLICT` 单赢家）。
5. **失败是否泄露信息**：存储错误仅映射为不可用，不泄露记录内容。

## 范围外

- 网关接线（claim→execute→finish、重复 key 返回旧结果、序列化失败「已执行但结果未知」语义，slice 4）。
- 记录归档与过期清理（TTL 字段落地，清理策略另行切片）。
- 与 ADR-0029 风险分级联动（slice 4/后续）。

## 证据

- `docs/evidence/SLICE-173-idempotency-store.txt`
