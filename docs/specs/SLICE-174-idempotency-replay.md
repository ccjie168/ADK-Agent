# SLICE-174 网关幂等重放与序列化失败语义

状态: gated
依据: ADR-0034（Accepted 2026-11-19）决定 3/5 / slice 3：网关按
`idempotency_key → execution record → result` 去重，重复调用返回上次结果不再执行；序列化失败时记录按
「执行成功但结果未知」处理，重试返回该状态而非重复执行。

## 意图

1. `ToolExecutionRecord` 增加 `claim_id: str | None = None`，用于区分「本次 claim 赢家」与「并发在途」。
2. `FunctionToolGateway` 增加 `idempotency: ToolIdempotencyStore | None` 与
   `idempotency_ttl_seconds: int = 86400`。
3. 写工具（`requires_idempotency`）且配置了存储时：claim → 已存在终态则重放（`completed` 返回旧结果、
   `unknown` 抛「结果未知」）、非我方的 `claimed` 抛「在途冲突」；赢家执行后 `finish("completed")`。
4. 输出无法 JSON 序列化时 `finish("unknown")` 并抛专用异常，重试返回「结果未知」而非重复执行。
5. `build_tool_gateway_app` 捕获新异常映射到 502 `tool_result_unknown` 与 409 `idempotency_in_progress`。

## 契约（先改）

- 无对外 schema 变更（`claim_id` 为内部存储字段，不进 `export_contracts.py`）。

## 完成判据

- [ ] 重复 key 返回旧结果且只执行一次 -> `test_duplicate_key_replays_result`
- [ ] 序列化失败记录 unknown 且重试不重执行（502 `tool_result_unknown`） -> `test_serialization_failure_records_unknown`
- [ ] 并发在途冲突映射 409 -> `test_gateway_in_progress_409`
- [ ] 只读工具无 key 仍正常 -> `test_read_tool_unaffected`
- [ ] 无存储时写工具带 key 正常执行 -> `test_no_store_executes_once`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上重复 key 会重复执行，序列化失败不留 `unknown` 记录

## 5 问威胁建模

1. **数据**：写工具执行记录与结果，`idempotency_key`（调用方可控）。
2. **调用方**：工具网关 `/v1/invoke`、父进程沙箱执行器。
3. **信任边界**：HTTP 请求到网关执行与存储。
4. **恶意输入最坏结果**：并发重复执行写工具（缓解：`claim_id` + `os.link`/`ON CONFLICT` 单赢家）。
5. **失败是否泄露信息**：仅 502/409 错误码，不泄露结果或记录内容。

## 范围外

- CLI 的 `--idempotency-dir`/`--idempotency-db` 接线（随后切片）。
- 与 ADR-0029 风险分级联动（L3/L4 强制幂等，slice 4）。
- 记录归档与过期清理。

## 证据

- `docs/evidence/SLICE-174-idempotency-replay.txt`
