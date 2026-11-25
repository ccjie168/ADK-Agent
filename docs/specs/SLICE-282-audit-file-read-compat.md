# SLICE-282 `--audit-file` 读取兼容裸事件

状态: gated
依据: PROGRESS 第 16 条既有缺口（`--audit-file` 与 `FileAuditQuery` 不一致）

## 意图

`console --audit-file PATH`（以及同样走 `JsonlAuditSink` 的网关命令）写的是**裸 `AuditEvent`** 行，
而读取端 `query_events` 只按 `AuditRecord` 解析。文件里一旦有事件，`/api/audit`、`/api/runs`
与 trace 查询就会 500 `audit_unavailable`。

本切片让**读取端同时接受两种行**：

- 链记录（`{"event": ..., "prev_hash", "hash", ...}`，`serve-audit --out` 与 `--audit-db` 的形状）；
- 裸事件（`JsonlAuditSink` 的输出）。

解析顺序：先按 `AuditRecord`，失败再按 `AuditEvent`；两者都失败时保留原有行为
（当前文件最后一行视为半写行跳过，其他位置抛错）。`verify-audit` 的语义不变：仍然只认链记录，
`--audit-file` 的产物不是链，需要链式审计时用 `serve-audit --out`。

不改变任何写入格式，因此没有数据迁移。

## 契约（先改）

- `docs/contracts/cli.md`「审计后端选择」：写明 `--audit-file` 写裸事件、读取端兼容两种行、
  `verify-audit` 只认链记录。
- `docs/contracts/audit_chain.md`：新增「兼容读取」一节，说明查询端接受裸事件、哈希校验不变。
- `docs/contracts/console.md`：`GET /api/audit` 注明读取兼容。

## 完成判据

- [ ] 裸事件文件可按时间读出 -> `test_query_events_reads_bare_events`
- [ ] 裸事件文件仍按租户过滤 -> `test_query_events_filters_bare_events`
- [ ] 裸事件文件同样跳过半写的最后一行 -> `test_query_events_skips_a_half_written_bare_line`
- [ ] 中间行的坏 JSON 仍然报错 -> `test_query_events_rejects_a_corrupt_middle_line`
- [ ] 链记录读取无回归 -> `test_query_events_still_reads_chained_records`
- [ ] 控制台用自己的 JSONL 文件返回 200 与事件 -> `test_console_audit_lists_its_own_jsonl_file`

## 反例

实现前，裸事件文件上的 `query_events` 抛 `ValidationError`，`/api/audit` 返回 500
`audit_unavailable`；链记录读取与坏行用例在旧代码上通过，作为回归保护（证据里注明）。

## 5 问威胁建模

1. **数据**：审计事件（租户、主体、动作、目标、状态、时间）；不含 prompt 或参数原文。
2. **调用方**：控制台与审计服务的读取端；权限检查仍在接口层（`audit.read` / OIDC 租户）。
3. **信任边界**：审计文件在宿主盘上。接受裸事件不给写入者新增能力：能写文件的人本来就能追加
   一条形状正确的链记录，而读取端从不做链校验。
4. **恶意输入**：两种解析都走 pydantic（`extra="forbid"`、时间必须带时区）；坏行按原规则报错或
   仅在末尾跳过；不会执行任何内容。
5. **失败是否泄露信息**：错误仍是 `audit_unavailable` 或 pydantic 校验错误，不包含文件内容。

## 范围外

- 把 `--audit-file` 改成写链记录（涉及格式迁移，另行决定）。
- `verify-audit` 接受裸事件。
- 审计轮转与签名语义。

## 证据

- `docs/evidence/SLICE-282-audit-file-read-compat.txt`
