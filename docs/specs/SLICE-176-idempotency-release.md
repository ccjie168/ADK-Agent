# SLICE-176 执行失败回滚幂等 claim

状态: gated
依据: ADR-0034 决定 3 的收尾：写工具执行抛异常时，已 claim 的 `claimed` 记录会滞留到 TTL，导致重试
命中 `claimed` 返回 409 `idempotency_in_progress`。本切片给存储增加 `release` 并在执行失败时释放 claim，
使瞬时失败可重试。

## 意图

1. `ToolIdempotencyStore` 协议增加 `release(tenant, tool_id, idempotency_key) -> None`。
2. `FileToolIdempotencyStore.release` 删除对应记录文件（幂等，不存在不报错）。
3. `PostgresToolIdempotencyStore.release` 删除对应行（幂等）。
4. `FunctionToolGateway.invoke` 在工具执行抛异常时，若本次赢得了 claim，则 best-effort 释放 claim
   （释放失败不掩盖原始异常），使重试可重新 claim 执行。

## 契约（先改）

- 无对外 schema 变更（存储内部方法）。

## 完成判据

- [ ] release 删除文件记录且幂等 -> `test_release_removes_record`
- [ ] release 不存在的 key 不报错 -> `test_release_missing_is_noop`
- [ ] 执行失败后重试可重新执行 -> `test_execution_failure_releases_claim`
- [ ] 序列化失败仍保留 unknown（不 release） -> `test_serialization_failure_keeps_unknown`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上执行失败的写工具重试命中 `claimed` 返回 409，且 `release` 方法不存在

## 5 问威胁建模

1. **数据**：写工具执行记录的生命周期。
2. **调用方**：工具网关。
3. **信任边界**：网关执行到存储。
4. **恶意输入最坏结果**：执行失败后 claim 滞留导致重试被永久阻塞（缓解：best-effort release，重试可重新 claim）。
5. **失败是否泄露信息**：release 失败仅记日志，不改变对外错误。

## 范围外

- CLI 的 `--idempotency-dir`/`--idempotency-db` 接线（随后切片）。
- 记录归档与过期清理。

## 证据

- `docs/evidence/SLICE-176-idempotency-release.txt`
