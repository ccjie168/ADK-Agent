# SLICE-171 写工具幂等字段（write / idempotency_required）

状态: gated
依据: ADR-0034（Accepted 2026-11-19）决定 1 / slice 1：`ToolSpec`/`ToolEntry` 增加 `write` 与
`idempotency_required` 字段，写工具默认要求幂等。本切片只加字段，缺 key 拒绝与存储后置。

## 意图

1. `ToolSpec`（tools/registry.py）增加 `write: bool = False` 与 `idempotency_required: bool = False`。
2. `ToolEntry`（tools/catalog.py）增加同名字段，默认 `False`。
3. 两个类型增加计算属性 `requires_idempotency`：`write or idempotency_required`（写工具默认要求幂等）。
4. 无对外 schema 变更（`ToolSpec`/`ToolEntry` 为内部类型，不进入 `export_contracts.py`）。

## 契约（先改）

- 无 schema 变更；`docs/contracts/tool_gateway.md` 暂不改（缺 key 拒绝在 slice 2 落地时补）。

## 完成判据

- [ ] `ToolSpec` 默认 `write`/`idempotency_required` 均为 False -> `test_tool_spec_write_fields_default_false`
- [ ] `ToolSpec(write=True)` 的 `requires_idempotency` 为 True -> `test_tool_spec_write_requires_idempotency`
- [ ] `ToolSpec(idempotency_required=True)` 的 `requires_idempotency` 为 True -> `test_tool_spec_explicit_idempotency_required`
- [ ] `ToolEntry` 接受并保留 `write`/`idempotency_required` -> `test_tool_entry_write_fields`
- [ ] `ToolEntry(write=True)` 的 `requires_idempotency` 为 True -> `test_tool_entry_write_requires_idempotency`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `ToolSpec`/`ToolEntry` 无 `write`/`idempotency_required`/`requires_idempotency`

## 5 问威胁建模

1. **数据**：工具元数据的写语义与幂等要求。
2. **调用方**：工具目录、工具网关注册、控制台目录视图。
3. **信任边界**：manifest/catalog schema 到网关执行。
4. **恶意输入最坏结果**：写工具被误标只读而绕过幂等（缓解：字段默认 false，`requires_idempotency` 由 write 推导）。
5. **失败是否泄露信息**：纯类型字段，无新错误面。

## 范围外

- `ToolRequest.idempotency_key` 字段与 schema（slice 2）。
- 缺 key 拒绝、幂等存储、重复 key 重放、序列化失败语义（slice 2/3）。
- 与 ADR-0029 风险分级联动（slice 4）。

## 证据

- `docs/evidence/SLICE-171-write-idempotency-fields.txt`
