# SLICE-299 模型页提供方与密钥表单、手册章节

状态: active
依据: ADR-0045（方案 A 记录 + 方案 B 只写密钥）

## 意图

控制台「模型」页增加模型提供方管理：列出记录、查看掩码、创建/更新记录；
`--model-key-entry` 开启时，admin 可以只写保存密钥与吊销密钥。
`docs/guides/console-ui.html` 的手册「模型」一节补上提供方与密钥的用法与错误码。
接口与运行时解析已在 SLICE-296/297/298 交付，本切片只做界面与手册。

## 契约（先改）

沿用既有契约，不新增接口：

- `GET /api/model-providers`（`model.read`）：`{providers, key_entry}`。
- `PUT /api/model-providers/{id}`（`model.write`）。
- `PUT/DELETE /api/model-providers/{id}/key`（`model.write`，仅在 `key_entry` 为真时展示表单）。
- 页面错误用固定中文，按服务端 `error` 码映射：`invalid_provider`、`provider_not_found`、
  `model_key_entry_disabled`、`model_key_entry_unavailable`、`invalid_key`、`forbidden`。
- 密钥框 `type="password"`、`autocomplete="off"`，保存后清空输入，只显示掩码。

## 完成判据

- [ ] 模型页读取并展示提供方记录与掩码 -> `test_model_view_reads_providers`
- [ ] 表单创建/更新记录并映射错误 -> `test_model_view_saves_provider`
- [ ] 密钥保存与吊销只在开启时出现 -> `test_model_view_manages_keys`
- [ ] 无 `model.write` 时隐藏写操作 -> `test_model_view_gates_on_capabilities`
- [ ] `key_entry` 为假时不显示密钥表单 -> `test_model_view_respects_key_entry`
- [ ] 构建产物包含新界面 -> `test_model_provider_ui_is_built`
- [ ] 手册补提供方与密钥章节与错误码 -> `test_guide_documents_model_providers`
- [ ] `--full` 门禁通过

## 反例

master 上 `ModelView.vue` 只有调用统计与默认模型，没有 `/api/model-providers`；手册「模型」
一节只有两句话；`web/dist` 里搜不到提供方界面字符串。七个用例中六个在 master 上失败；
`test_model_view_gates_on_capabilities` 通过，因为旧的默认模型表单已有 `canWrite` 门控。

## 5 问威胁建模

1. **数据**：页面只显示掩码与引用，不接收或显示明文以外的历史值；密钥输入用密码框。
2. **调用方**：读用 `model.read`，写与密钥用 `model.write`；无权限时只读视图。
3. **信任边界**：浏览器仍不需要签名密钥；所有写操作走控制台已鉴权接口。
4. **恶意输入**：前端只做必填与长度提示，最终校验仍由服务端返回固定错误码。
5. **失败是否泄露信息**：页面只显示固定中文错误，不回显服务端消息或值。

## 范围外

- 运行时解析（SLICE-298 已交付）。
- 多租户记录、Postgres 后端、模型网关服务配置。
- 密钥轮换向导（重新保存即轮换）。

## 证据

- `docs/evidence/SLICE-299-model-page.txt`
- `docs/evidence/ui/SLICE-299-model.png`
