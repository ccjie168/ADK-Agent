# SLICE-298 模型提供方运行时解析（方案 A + B 接线）

状态: active
依据: ADR-0045（解析顺序：记录 > 环境变量 > 内置默认；方案 B 密钥只在运行时解密）

## 意图

让模型提供方记录真正影响模型构建：`build_model()` 解析默认模型或显式模型时，
若存在同 `kind` 与同模型名的启用记录，就用记录里的 `base_url` 和密钥；
密钥优先取方案 B 加密录入（有 KEK 时解密），否则取记录的 `secret_ref` 指向的环境变量。
记录缺失、停用或解密失败时回落到现有的环境变量与内置默认。控制台与四个服务命令
都能通过 `--model-providers-dir` 接入；页面表单与手册章节留给 SLICE-299。

## 契约（先改）

`docs/contracts/console.md`：`GET /api/model-providers` 的响应增加顶层
`key_entry`（布尔，来自 `--model-key-entry`），前端据此决定是否显示密钥录入。

`docs/contracts/cli.md` 新增「模型提供方解析（ADR-0045）」一节：

- `console`、`serve`、`serve-many`、`serve-a2a`、`serve-triggers` 接受
  `--model-providers-dir DIR`。
- 解析顺序：启用记录（同 `kind`、同模型名，模型名可带 `kind:` 前缀）提供
  `api_base` 与密钥；无匹配记录时用环境变量；最后是内置默认。
- 记录密钥来源：先看 `<DIR>/keys/<provider_id>.json`（方案 B，需要 KEK 后端；
  KEK 缺失或解密失败跳过密钥并写日志），否则 `secret_ref` 映射到
  `ADK_SECRET_<TENANT>_<NAME>` 环境变量。
- 同一 `(kind, 模型名)` 有多条启用记录时按 `provider_id` 排序取第一条。
- 记录只补充缺失的 `api_key`/`api_base`，不改变显式指定的模型名。

## 完成判据

- [ ] 有记录时 `resolve_model_config` 用记录的 key 与 base_url -> `test_resolve_model_config_uses_record`
- [ ] 显式 `kind:` 前缀与裸模型名都能匹配 -> `test_provider_lookup_normalizes_prefix`
- [ ] 停用记录与其他 kind 不参与 -> `test_provider_lookup_ignores_disabled_and_other_kind`
- [ ] 方案 B 密文密钥可解密使用，磁盘仍无明文 -> `test_provider_lookup_uses_stored_key`
- [ ] 无 KEK 时回落到 `secret_ref` 环境变量 -> `test_provider_lookup_falls_back_to_env_ref`
- [ ] 解密失败跳过密钥并写 `model.key_failed` -> `test_provider_lookup_audits_decrypt_failure`
- [ ] 记录缺失时保持现有默认行为 -> `test_resolve_model_config_without_records`
- [ ] 列表响应顶层带 `key_entry` 开关 -> `test_key_entry_reports_flag`
- [ ] 五个命令都接受 `--model-providers-dir` -> `test_model_provider_flags_on_commands`
- [ ] `--full` 门禁通过

## 反例

实现前 `resolve_model_config`/`set_provider_lookup`/`FileProviderLookup` 都不存在，
`serve*` 不认识 `--model-providers-dir`；上面的用例在 master 上失败（ImportError 与
argparse 退出 2）。

## 5 问威胁建模

1. **数据**：记录元数据、`secret://` 引用、方案 B 密文；运行时解出的明文只存在于内存。
2. **调用方**：解析发生在进程内，没有新增网络入口；写记录/密钥仍走控制台 RBAC。
3. **信任边界**：读取的目录由运维给定；文件名与记录 id 走既有安全校验。
4. **恶意输入**：记录文件损坏时跳过该记录并记日志；解密失败 fail-closed 到环境变量。
5. **失败是否泄露信息**：日志与审计只有 provider_id、错误码与异常类型，不含值或密文。

## 范围外

- 控制台「模型」页表单、`GET /api/model-providers` 之外的 UI（SLICE-299）。
- 手册章节（SLICE-299）。
- 模型网关服务（`serve-model-gateway`）的 provider 配置，它走自己的 `--provider`。
- 多租户记录与 Postgres 后端。

## 证据

- `docs/evidence/SLICE-298-model-runtime.txt`
