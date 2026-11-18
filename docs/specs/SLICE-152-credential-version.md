# SLICE-152 凭据审计版本号的共享与安全化

状态: gated
依据: SLICE-151 的验证代理指出控制面 `credential.register|disable` 审计仍直接拼接 key id，
不安全的 key id 会让 `AgentRef` 校验失败；同时 providers 里有一份重复的安全字符集正则。

## 意图

1. `core/credentials.py` 新增 `credential_version(key_id)`：空值返回 `credential`；安全字符集内
   返回 `credential.<key id>`；否则返回 `credential.<sha256 前 12 位>`。
2. providers 与注册表服务共用这一个函数，删除重复正则。
3. 控制面在密钥 id 为 `prod/key` 这类值时仍能写出 `credential.register`/`disable` 审计，
   不再抛 `ValidationError`。

## 契约（先改）

- `docs/contracts/credentials.md` 的 version 规则已覆盖；本切片不改接口。

## 完成判据

- [x] 版本号对 None、空串、安全值与不安全值都稳定 -> `test_credential_version_is_always_schema_safe`
- [x] 不安全 key id 下控制面注册仍审计且不泄露原始 id -> `test_register_with_an_unsafe_key_id_still_audits`
- [x] 全量门禁通过

## 反例

- [x] 基线控制面对不安全 key id 构造 `AgentRef` 失败，注册可能 500 或丢失审计
- [x] 基线 providers 与注册表各有一份正则，规则可能漂移

## 5 问威胁建模

1. **数据**：key id、审计事件。
2. **调用方**：控制面写入与运行时解析。
3. **信任边界**：审计只写元数据。
4. **恶意输入最坏结果**：不安全 key id 让审计失败（缓解：哈希化 version）；两份正则漂移
   （缓解：单一实现）。
5. **失败是否泄露信息**：version 不含原始不安全 id。

## 范围外

- 控制台注册审计的 version 固定为 `credential`，不涉及 key id。

## 证据

- `docs/evidence/SLICE-152-credential-version.txt`
