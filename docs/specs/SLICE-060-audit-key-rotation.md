# SLICE-060 审计签名密钥轮换

状态: merged
依据: SLICE-053，`docs/contracts/audit_record.schema.json`，`docs/contracts/cli.md`。

## 意图（要什么，不写怎么写）

审计签名只有一把密钥。换密钥后旧记录全部验不过，等于不能轮换。这一刀给记录加密钥 id，签名和验签支持多个密钥。

- `AuditRecord` 增加可选 `kid`，没有时是 `null`。
- 新增 `src/adk_agent/audit/keyring.py`：`SigningKeyring`、`KeyringError`。
- 密钥环是一个 JSON 值，从 `ADK_AUDIT_KEYRING` 读：`{"active": "<kid>", "keys": {...}, "legacy": "<kid>"}`。`legacy` 可选。
- `AuditPipeline` 接受 `keyring`，与 `signing_key` 互斥。给 keyring 时新记录用 `active` 密钥签名并写 `kid`；只给 `signing_key` 时行为不变，`kid` 为 `null`。
- `verify_audit_file` 接受 `keyring`。按记录的 `kid` 选密钥；没有 `kid` 的记录用 `legacy` 指定的密钥；未知 `kid` 或无法选密钥时报 `AuditSignatureInvalid`。
- `serve-audit` 和 `verify-audit` 读同一套环境变量。两个变量同时设置时退出 1。
- 轮换流程配合密钥环完成：加新密钥、`active` 指向新密钥、保留旧密钥、旧历史没有 `kid` 时设置 `legacy`。

## 新增文件

- `src/adk_agent/audit/keyring.py`
- `tests/audit/test_key_rotation.py`
- `docs/evidence/SLICE-060-audit-key-rotation.txt`

## 修改文件

- `src/adk_agent/core/audit.py`：`kid`
- `src/adk_agent/audit/pipeline.py`：`keyring` 参数与按 `kid` 验签
- `src/adk_agent/audit/__init__.py`：导出
- `src/adk_agent/cli.py`：`ADK_AUDIT_KEYRING`
- `docs/contracts/audit_record.schema.json`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditRecord:
  {..., "signature": hex64 | null, "kid": "<key id>" | null}

SigningKeyring:
  active: str            # 必须存在于 keys
  keys: dict[str, str]   # kid 匹配 ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$，值非空
  legacy: str | null     # 可选，必须存在于 keys

签名: HMAC-SHA256(key=active 对应密钥, message=record.hash)，不变
验签: key = keys[kid]；kid 为空 -> keys[legacy]；选不到 -> AuditSignatureInvalid
```

## 完成判据（可执行）

- [x] 新记录带 `kid` 且用密钥环可验 -> `tests/audit/test_key_rotation.py::test_records_carry_kid`
- [x] 未知 `kid` 被拒 -> `tests/audit/test_key_rotation.py::test_unknown_kid_rejected`
- [x] 无 `kid` 的旧记录用 `legacy` 验 -> `tests/audit/test_key_rotation.py::test_legacy_key_for_old_records`
- [x] 没给 `legacy` 时旧记录被拒 -> `tests/audit/test_key_rotation.py::test_missing_legacy_rejected`
- [x] 轮换后新旧记录一起通过 -> `tests/audit/test_key_rotation.py::test_rotation_keeps_both_keys`
- [x] 删掉旧密钥后旧记录被拒 -> `tests/audit/test_key_rotation.py::test_old_key_removal_detected`
- [x] 密钥环要求 active 存在 -> `tests/audit/test_key_rotation.py::test_keyring_requires_active_key`
- [x] 密钥环拒绝空密钥 -> `tests/audit/test_key_rotation.py::test_keyring_rejects_empty_key`
- [x] 密钥环拒绝非法 kid -> `tests/audit/test_key_rotation.py::test_keyring_rejects_bad_kid`
- [x] 管道拒绝同时给 keyring 和 signing_key -> `tests/audit/test_key_rotation.py::test_pipeline_rejects_two_key_modes`
- [x] `verify-audit` 用密钥环通过 -> `tests/audit/test_key_rotation.py::test_cli_verify_with_keyring`
- [x] 两个环境变量同时设置退出 1 -> `tests/audit/test_key_rotation.py::test_cli_rejects_both_env`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.audit import SigningKeyring` -> 当前 `ImportError`
- [x] 反例 2：`AuditRecord(..., kid="k1")` -> 当前校验失败（字段不存在，`extra="forbid"`）
- [x] 反例 3：`verify_audit_file(path, keyring=...)` -> 当前 `TypeError`

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/audit_record.schema.json`（新增 `kid`）与 `docs/contracts/cli.md`（serve-audit、verify-audit 的密钥环与轮换流程）。

## 5 问威胁建模（10 分钟）

1. **数据**：审计记录、签名、密钥 id、密钥本身。
2. **调用方**：运维和审计服务进程。
3. **信任边界**：环境变量到进程；审计文件到验签器。
4. **恶意输入最坏结果**：伪造 `kid` 指向另一把密钥（缓解：签名覆盖 `hash`，用错密钥必然不匹配）；轮换时提前删旧密钥导致历史验不过（契约写明保留顺序）；把密钥写进仓库或命令行（仍只从环境变量读）；非法密钥环静默降级成不验签（构造失败即退出 1）。
5. **失败是否泄露信息**：报错只给记录序号和租户，不给密钥或 `kid` 内容。

## 范围外

- 密钥托管、KMS、自动轮换调度。
- 对已有记录重新签名。
- 哈希链本身的跨密钥迁移。

## 证据

- 反例红: `docs/evidence/SLICE-060-audit-key-rotation.txt` 的 red 段
- 实现后绿: 同文件 green 段，43 个审计用例通过，全量 704 passed
- 实机: 同文件 live 段。旧密钥写的 3 条无 `kid` 记录，密钥环轮换后追加 2 条 `kid=k2`，带 `legacy` 的密钥环验证 5 条通过；删掉旧密钥在记录 0 报错；单密钥模式在记录 3 报错；两个环境变量同时设置退出 1
