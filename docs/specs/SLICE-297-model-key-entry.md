# SLICE-297 模型密钥只写录入（方案 B）

状态: active
依据: ADR-0045（2026-11-25 确认 A + B 都做，方案 B 显式开启并接受五条前提）

## 意图

在 `--model-key-entry` 显式开启时，admin 可为已存在的模型提供方记录提交一次 `api_key`；
平台用现有密钥后端（本地 KEK 或 Vault/OpenBao Transit）信封加密保存，读接口只回掩码，
任何接口不回明文或密文。本切片只做录入、掩码、吊销与解密失败审计，
运行时把密钥接到模型构建、页面表单与手册留给 SLICE-298。

## 契约（先改）

`docs/contracts/console.md`：

- `GET /api/model-providers` 每项增加 `key_configured`（布尔）与 `key_hint`（掩码或 null）；
  密钥录入未开启时固定 `false` / `null`。
- `PUT /api/model-providers/{provider_id}/key`，请求体 `{"api_key": string}`，返回
  `{provider_id, key_configured, key_hint, updated_at, updated_by}`。
  - 需要 `model.write`，缺能力 403 `forbidden`（先于开关检查）。
  - 未开启密钥录入 503 `model_key_entry_disabled`。
  - 密钥后端未配置 503 `model_key_entry_unavailable`。
  - 提供方记录不存在 404 `provider_not_found`。
  - `api_key` 不是字符串、为空或超过 512 字符 400 `invalid_key`。
  - 成功写一条 `model.key.set` 审计：只有 provider_id 与类型，没有密钥值或密文。
- `DELETE /api/model-providers/{provider_id}/key`，返回 `{provider_id, key_configured: false}`，
  幂等；写 `model.key.revoke` 审计。
- 密文只存在 `<providers>/keys/<provider_id>.json`，AAD 为 `adk-model-provider:<provider_id>`。

CLI：`console --model-key-entry` 需要同时给 `--model-providers-dir`；该目录解析后落在
含 `.git` 的仓库根内时拒绝启动（退出 1）。未配置 KEK 时服务仍可启动，PUT 返回 503；
DELETE 不需要解密，照常吊销。

## 完成判据

- [ ] 有密钥的记录列表给出掩码、无密钥的给 null -> `test_key_entry_lists_masked_hint`
- [ ] 写入后磁盘只有密文，响应与列表都没有明文或密文 -> `test_key_entry_writes_ciphertext_only`
- [ ] 未开启开关时 503 -> `test_key_entry_requires_flag`
- [ ] 没有密钥后端时 PUT 503、DELETE 仍可吊销 -> `test_key_entry_requires_backend`
- [ ] 后端加密失败同样 503 而非 500 -> `test_key_entry_backend_failure_is_unavailable`
- [ ] 未知提供方 404 -> `test_key_entry_unknown_provider`
- [ ] 空 key 与超长 key 400 -> `test_key_entry_rejects_invalid_key`
- [ ] 吊销幂等并写审计 -> `test_key_entry_revoke`
- [ ] 短于 8 字符的 key 掩码不暴露任何字符 -> `test_key_entry_masks_short_keys_fully`
- [ ] 解密失败写 `model.key_failed` 且不含密钥值 -> `test_key_resolver_audits_decrypt_failure`
- [ ] 损坏的密钥记录同样审计并转 `ModelKeyUnavailable` -> `test_key_resolver_audits_unreadable_record`
- [ ] 仓库内存储目录拒绝启动 -> `test_key_entry_rejects_repo_directory`
- [ ] `--full` 门禁通过

## 反例

实现前没有 key 存储、端点与开关；上述用例在 master 上失败（未知参数退出 2、
`/api/model-providers/{id}/key` 404 / 405、列表没有掩码字段）。

## 5 问威胁建模

1. **数据**：模型 API Key 明文只在请求体与加密瞬间存在；持久层只有信封密文与掩码。
2. **调用方**：只有 admin（`model.write`）能写；默认关闭，需部署显式开启。
3. **信任边界**：密文目录在仓库外（启动检查），文件写入用临时文件 + `os.replace`；
   文件名走 `safe_join` 与安全名校验。
4. **恶意输入**：非法 id、空/超长 key、非对象请求体返回固定错误码；掩码只取首尾片段。
5. **失败是否泄露信息**：错误与审计只给错误码与 provider_id；日志不打印 key、密文或掩码以外的字段。

## 范围外

- 运行时用录入的密钥构建模型（SLICE-298）。
- 控制台「模型」页表单与使用手册章节（SLICE-298）。
- 多租户模型记录（当前记录无 tenant 字段）与 Postgres 存储。
- 密钥轮换命令（重新 PUT 即轮换；与 Vault 的 rewrap 迁移复用凭据流程）。

## 证据

- `docs/evidence/SLICE-297-model-key-entry.txt`
