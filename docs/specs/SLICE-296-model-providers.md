# SLICE-296 模型提供方记录与接口（方案 A）

状态: active
依据: ADR-0045（2026-11-25 确认，默认方案 A：纯引用）

## 意图

让控制台保存模型提供方记录：`provider_id`、类型、模型、可选 base_url 与 `secret_ref`。
本切片只做记录与接口，不解析密钥、不改变运行时取 key 的方式（密钥仍来自环境变量）；
运行时接引用与只写加密录入分别在 SLICE-297/298。

## 契约（先改）

`docs/contracts/console.md` 新增：

- `GET /api/model-providers` -> `{"providers": [ModelProvider]}`，需要 `model.read`；
  未配置存储返回 404 `model_providers_not_configured`。
- `PUT /api/model-providers/{provider_id}` -> `ModelProvider`，需要 `model.write`；
  校验 `provider_id` 安全名、`kind` 在 `litellm|gemini|claude|vertex`、
  `model` 通过 `is_valid_model_spec`、`secret_ref` 形如 `secret://tenant/name`；
  非法返回 400 `invalid_provider`；写一条 `model.configure` 审计，只含 provider_id、
  provider_kind 与 secret_ref 引用键名。
- CLI `console --model-providers-dir DIR`。

## 完成判据

- [ ] 存储读写往返一致 -> `test_provider_store_roundtrip`
- [ ] 列表需要 model.read 且返回记录 -> `test_provider_api_lists_records`
- [ ] 写入需要 model.write -> `test_provider_api_requires_model_write`
- [ ] 非法 provider_id 返回 400 -> `test_provider_api_rejects_unsafe_id`
- [ ] provider_id 恰为 64 字符可写入并落盘 -> `test_provider_api_accepts_max_length_id`
- [ ] provider_id 65 字符返回 400 -> `test_provider_api_rejects_overlong_id`
- [ ] 非法 secret_ref 返回 400 -> `test_provider_api_rejects_bad_secret_ref`
- [ ] 审计含 provider_kind 与 secret_ref 键名、不含密钥材料 -> `test_provider_api_audits_without_key_material`
- [ ] 未配置存储返回 404 -> `test_provider_api_404_when_store_missing`
- [ ] `--full` 门禁通过

## 反例

实现前没有该类型、存储与端点；七个用例在 master 上失败（404 / 缺少路由 / 缺少存储类）。

## 5 问威胁建模

1. **数据**：提供方元数据与 `secret://` 引用；不含密钥值。
2. **调用方**：读需要 `model.read`，写需要 `model.write`（仅 admin）。
3. **信任边界**：文件存储在部署目录，名称走 `safe_join`；不跟随符号链接写入。
4. **恶意输入**：非法 id、未知 kind、非法模型规范、非法引用都返回 400，固定错误码。
5. **失败是否泄露信息**：错误信息只提字段名，不回显值或路径。

## 范围外

- 密钥解析与运行时接入（SLICE-297）。
- 只写加密录入（SLICE-297/298）。
- Postgres 存储（文件存储先交付，契约注明）。
- 前端页面（SLICE-298）。

## 证据

- `docs/evidence/SLICE-296-model-providers.txt`
