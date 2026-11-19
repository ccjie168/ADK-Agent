# SLICE-175 风险分级联动：L3/L4 强制幂等

状态: gated
依据: ADR-0034（Accepted 2026-11-19）决定 4 / slice 4：L3/L4 写强制幂等；L2 写建议（可 opt-out）；
L1 只读不需要。本切片把 `risk_level` 引入 `ToolSpec`，并把 `idempotency_required` 改为三态，使
`requires_idempotency` 按风险分级推导。

## 意图

1. `ToolSpec`（tools/registry.py）增加 `risk_level: RiskLevel | None = None`。
2. `ToolSpec`/`ToolEntry` 的 `idempotency_required` 改为 `bool | None = None`（三态：None=未显式设置）。
3. `requires_idempotency` 推导规则：`risk_level in ("L3","L4")` 强制 True；否则 `idempotency_required`
   非 None 时取该值；否则回落到 `write`（写工具默认要求）。
4. 无对外 schema 变更（`ToolSpec`/`ToolEntry` 为内部类型）。

## 契约（先改）

- 无 schema 变更。

## 完成判据

- [ ] L4 写即使 opt-out 仍强制幂等 -> `test_l4_write_forces_idempotency_even_with_opt_out`
- [ ] L3 写强制幂等 -> `test_l3_write_forces_idempotency`
- [ ] L2 写默认为幂等 -> `test_l2_write_defaults_to_idempotent`
- [ ] L2 写可 opt-out -> `test_l2_write_can_opt_out`
- [ ] 只读工具不要求幂等 -> `test_read_tool_does_not_require_idempotency`
- [ ] 三态字段默认 None -> `test_idempotency_required_defaults_none`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `ToolSpec` 无 `risk_level` 字段，L4 写带 `idempotency_required=False` 不会强制幂等

## 5 问威胁建模

1. **数据**：工具的风险分级与幂等要求。
2. **调用方**：工具网关注册、控制台目录视图。
3. **信任边界**：工具元数据到网关执行。
4. **恶意输入最坏结果**：L3/L4 写被 opt-out 绕过幂等（缓解：risk_level 强制优先于 opt-out）。
5. **失败是否泄露信息**：纯字段推导，无新错误面。

## 范围外

- CLI 的 `--idempotency-dir`/`--idempotency-db` 接线（随后切片）。
- 执行失败回滚 claim（`release`/`delete`，随后切片）。
- 记录归档与过期清理。

## 证据

- `docs/evidence/SLICE-175-risk-idempotency-linkage.txt`
