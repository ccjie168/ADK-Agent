# SLICE-201 审计链以存储内容为准（文件模式）

状态: gated
依据: ADR-0037（Accepted 2026-11-21）决定 1-5 / 切片 1。

## 意图

1. 抽出 `canonical_event_json(payload)`：接受存储的事件 JSON 文本或对象，输出规范排序形式。
2. `record_hash` 接受事件文本、对象或 `AuditEvent`，一律走同一规范函数；写入路径只序列化一次，
   存什么就哈希什么。
3. 文件模式校验从每行里的事件对象重算，历史记录（包括 SLICE-188 之前写出的、缺少后加字段的记录）
   恢复可验。
4. 篡改事件内容仍然断链，检测能力不下降。

## 契约（先改）

- 新增 `docs/contracts/audit_chain.md`：链的记录结构、哈希口径（存储事件 JSON 的规范形式）、
  签名覆盖范围、字段演化规则（加字段不改哈希）。

## 完成判据

- [x] `record_hash` 对文本与对象给同一结果 -> `test_record_hash_accepts_stored_event_json`
- [x] 键顺序不同的 JSON 规范形式相同 -> `test_canonical_form_is_key_order_independent`
- [x] 非有限浮点下三种输入口径一致 -> `test_record_hash_matches_for_non_finite_floats`
- [x] 缺后加字段的历史记录仍可验签 -> `test_legacy_record_without_new_fields_verifies`
- [x] 在历史记录后继续追加，整链仍可验 -> `test_append_after_legacy_record_keeps_chain`
- [x] 篡改事件内容断链 -> `test_tampering_event_content_breaks_chain`
- [x] 全量门禁通过

## 反例

- [x] 基线上用当前模型重算历史事件会得到不同哈希（`AuditChainBroken`）
- [x] 若写入与哈希各序列化一次，任何一次字段顺序差异都会断链（回归用例覆盖同一序列化）

## 5 问威胁建模

1. **数据**：审计事件、前一记录哈希、记录哈希与签名。
2. **调用方**：写审计的进程与运行 `verify-audit` 的运维。
3. **信任边界**：存储内容 → 链验证；当前代码不再参与解释历史。
4. **恶意输入最坏结果**：改事件内容但保持哈希字段不变。缓解：哈希覆盖事件全部字段的规范形式，
   改动即断链；规范化只影响键序与空白，不丢弃任何字段。
5. **失败是否泄露信息**：断链与验签失败只报序号与租户。

## 范围外

- Postgres 模式与 live 用例（切片 2）。
- `verify-audit` 输出措辞与运维手册（切片 3）。
- 历史不一致记录的重签或迁移（ADR-0037 已否决）。

## 证据

- `docs/evidence/SLICE-201-audit-chain-canonical.txt`
