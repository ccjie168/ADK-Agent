# SLICE-188 模型审计字段：alias、实际模型、降级次数

状态: gated
依据: ADR-0033（Accepted 2026-11-19）决定 3 / slice 4：审计记录 alias + 实际模型 + 降级次数。

## 意图

1. `AuditEvent` 增加 `model_alias: str | None = None` 与 `fallback_count: int = 0`（`ge=0`）。
2. `emit_model_audit` 与 `_complete_once` 增加同名关键字参数并写入事件。
3. `complete` 的 alias 路径把 alias 与第几次尝试（降级次数）透传；直接路径保持缺省。
4. 重生成 `audit_event.schema.json`（`audit_record.schema.json` 内嵌事件，同步重生成）。

## 契约（先改）

- `docs/contracts/audit_event.schema.json`、`docs/contracts/audit_record.schema.json` 重生成。

## 完成判据

- [ ] 直接调用审计写入缺省值 -> `test_direct_call_audits_defaults`
- [ ] alias 调用审计记录 alias -> `test_alias_call_audits_alias`
- [ ] 降级调用审计记录降级次数 -> `test_fallback_audits_count`
- [ ] AuditEvent 拒绝负的 fallback_count -> `test_audit_rejects_negative_fallback_count`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `AuditEvent` 无 `model_alias`/`fallback_count`（extra_forbidden）

## 5 问威胁建模

1. **数据**：模型调用的 alias、实际模型与降级次数。
2. **调用方**：审计服务、控制台审计视图。
3. **信任边界**：网关审计到审计存储。
4. **恶意输入最坏结果**：降级绕过审计追溯（缓解：每次尝试都写审计，记录 alias 与尝试序号）。
5. **失败是否泄露信息**：字段不含提示内容，无新错误面。

## 范围外

- 控制台展示 alias/降级（后续 UI 切片）。
- 跨副本预算（slice 3 的已知缺口）。

## 证据

- `docs/evidence/SLICE-188-model-audit-fields.txt`
