# SLICE-202 审计链以存储内容为准（Postgres 模式）

状态: gated
依据: ADR-0037（Accepted 2026-11-21）决定 3、6 / 切片 2。

## 意图

1. Postgres 写入路径只序列化一次：`event_text` 同时用于算哈希与写 `jsonb`。
2. 校验路径从 `event::text` 的存储对象重算，不再用当前模型；历史行恢复可验。
3. live 用例锁定 `jsonb` 往返在规范形式下保真（含 `0.0`、大浮点、大整数与微秒时间戳）。

## 契约（先改）

- `docs/contracts/audit_chain.md` 已有 Postgres 说明，本切片不改契约文本。

## 完成判据

- [x] `jsonb` 往返后哈希仍等于存储值 -> `test_jsonb_roundtrip_hashes_the_stored_event`
- [x] 旧格式行的哈希按原样验证通过 -> `test_legacy_event_object_verifies_as_written`
- [x] 负零在规范形式里归一，不因 null 的符号断链 -> `test_canonical_form_folds_negative_zero`
- [x] 全量门禁通过

## 反例

- [x] 基线上旧格式行在 `verify_audit_database` 里抛 `AuditChainBroken`
- [x] 若仍用模型重算，`jsonb` 规范化会让历史行与新行在最坏情况下不一致

## 5 问威胁建模

1. **数据**：`adk_audit_records` 的事件 `jsonb`、哈希与签名。
2. **调用方**：写审计的进程与运行 `verify-audit --audit-db` 的运维。
3. **信任边界**：存储文本 → 链验证。
4. **恶意输入最坏结果**：直接改数据库里的 `event`。缓解：哈希按存储对象重算，任何改动断链；
   `jsonb` 键序规范化被规范函数吸收，不构成绕过。
5. **失败是否泄露信息**：断链只报序号与租户。

## 范围外

- `verify-audit` 输出措辞与手册（切片 3）。
- 历史不一致记录的迁移（已否决）。

## 证据

- `docs/evidence/SLICE-202-audit-chain-postgres.txt`
