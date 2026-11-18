# SLICE-151 解密失败审计的边界收口

状态: gated
依据: SLICE-150 的验证代理留下的低风险项：不安全的 key id 会让审计事件构造失败并被吞掉，
元数据提取在 try 之外，缺后端时可能审计到已停用的绑定。

## 意图

1. `credential.decrypt_failed` 的 `agent_ref.version` 对不符合安全字符集的 key id 使用
   SHA-256 前 12 位，保证审计一定写得出来；没有 key id 时仍是 `credential`。
2. 元数据与主体提取放进审计的 try 里，任何异常都只记日志，不改变 fail-closed 的
   `SecretNotFound`。
3. 带密文但无密钥后端时，审计优先选启用中的绑定，`target` 不会指向一条被停用的记录。
4. 契约写明 version 的回退规则；`rewrap` 帮助同时提到两个 keyring 变量。

## 契约（先改）

- `docs/contracts/credentials.md` 的审计字段说明。

## 完成判据

- [x] 不安全的 key id 仍写出审计，version 不含原始 key id -> `test_audit_sanitises_an_unsafe_key_id`
- [x] 缺后端时审计启用中的绑定 -> `test_missing_backend_audits_the_enabled_binding`
- [x] 原有审计与成功路径用例保持通过 -> `test_decrypt_failure_writes_an_audit_event`、`test_successful_resolution_does_not_audit`
- [x] 全量门禁通过

## 反例

- [x] 基线对 `prod/key` 这类 key id 构造 `AgentRef` 失败，审计被吞掉、事件数为 0
- [x] 基线在缺后端时审计 `encrypted[0]`，可能正是已停用的记录

## 5 问威胁建模

1. **数据**：key id、凭证引用、审计记录。
2. **调用方**：凭据解析路径。
3. **信任边界**：与 SLICE-150 相同，审计只写元数据。
4. **恶意输入最坏结果**：用恶意 key id 让审计静默丢失（缓解：哈希化 version）；
   审计异常掩盖 fail-closed（缓解：全部收进 try）。
5. **失败是否泄露信息**：version 不含原始 key id，错误码固定。

## 范围外

- 后端错误码细分与 invocation 主体归因（信息级缺口，另行评估）。

## 证据

- `docs/evidence/SLICE-151-audit-edge-cases.txt`
