# SLICE-172 写工具缺 idempotency_key 拒绝

状态: gated
依据: ADR-0034（Accepted 2026-11-19）决定 2 / slice 2（前半）：工具调用增加 `idempotency_key`，写工具
缺 key 直接拒绝（400），审计记 `idempotency_missing`。幂等存储后置到 slice 3。

## 意图

1. `ToolRequest`（core/tool.py）增加 `idempotency_key: str | None`（非空、≤128 字符，缺省 None）。
2. 重生成 `tool_gateway_request.schema.json`。
3. `FunctionToolGateway.invoke` 在策略放行后、审批检查前，对 `spec.requires_idempotency` 且缺 key 的
   调用审计 `idempotency_missing` 并抛专用异常。
4. `build_tool_gateway_app` `/v1/invoke` 捕获该异常返回 400 `{"error": "idempotency_missing"}`。

## 契约（先改）

- `docs/contracts/tool_gateway_request.schema.json` 重生成（`ToolRequest` 新增可选 `idempotency_key`）。

## 完成判据

- [ ] `ToolRequest` 接受 `idempotency_key` -> `test_tool_request_accepts_idempotency_key`
- [ ] `ToolRequest` 拒绝空 key -> `test_tool_request_rejects_empty_idempotency_key`
- [ ] 写工具缺 key 返回 400 -> `test_gateway_rejects_missing_idempotency_key`
- [ ] 只读工具缺 key 正常执行 -> `test_gateway_allows_read_tool_without_key`
- [ ] 写工具带 key 正常执行 -> `test_gateway_allows_write_tool_with_key`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `ToolRequest` 无 `idempotency_key` 字段，写工具缺 key 不报 `idempotency_missing`

## 5 问威胁建模

1. **数据**：工具调用的幂等键与写工具元数据。
2. **调用方**：工具网关 `/v1/invoke`、父进程沙箱执行器。
3. **信任边界**：HTTP 请求体到网关执行。
4. **恶意输入最坏结果**：写工具缺 key 被静默执行（缓解：`requires_idempotency` 由 write 推导，网关集中拒绝）。
5. **失败是否泄露信息**：仅 400 `idempotency_missing`，不泄露内部细节。

## 范围外

- 幂等存储（文件 + Postgres）、重复 key 重放（slice 3）。
- 序列化失败语义（slice 3）。
- 与 ADR-0029 风险分级联动（L3/L4 强制，slice 4）。
- 父进程沙箱执行器为写工具注入 key（当前无工具标记 write=true，slice 4 落地）。

## 证据

- `docs/evidence/SLICE-172-idempotency-key-reject.txt`
