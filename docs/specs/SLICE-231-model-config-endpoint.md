# SLICE-231 控制台 model-config 端点 + 管理员 UI

状态: gated
依据: ADR-0040 MVP 第 2 项（控制台端点 + 管理员 UI）

## 意图

1. `build_console_app` / `run_console` 新增 `model_config_store` 参数（`ModelConfigStore | None`），
   控制台暴露 `GET /api/model-config`（`model.read`，admin + operator）与 `PUT /api/model-config`
   （`model.write`，admin-only）。
2. `GET` 返回当前全局默认模型字符串（优先持久化 store，其次运行时生效值）。`PUT` 校验 provider
   前缀合法，写 store（若配置）+ 更新内存 override，并写一条 `model.configure` 审计。
3. 模型面板加「设置默认模型」输入框与按钮，按钮按 `model.write` 能力显隐（仅 admin）。CLI 加
   `--model-config-dir` / `--model-config-db` 两个开关与 `_model_config_store(args)` 工厂。

## 契约（先改）

- `docs/contracts/console.md` 新增 `GET /api/model-config` 与 `PUT /api/model-config` 两节。
- `models/__init__.py` 新增公开谓词 `is_valid_model_spec(spec) -> bool`：空串或含非法 provider 前缀
  （`:` 前段不在 `gemini|litellm|claude|vertex`）返回 `False`，无冒号按 litellm 接受。属框架库公共
  接口，随本切片在契约 `docs/contracts/models.md`（如有）或本切片说明中记录。

## 完成判据

- [x] 权限：GET 缺 `model.read` 返回 403 -> `test_model_config_get_requires_model_read`
- [x] 权限：PUT 非 admin（operator 有 read 无 write）返回 403 -> `test_model_config_put_admin_only`
- [x] 读：store 有值时 GET 返回该值 -> `test_model_config_get_returns_stored`
- [x] 写：PUT 合法值后 GET 一致，且落 `model.configure` 审计 -> `test_model_config_put_persists_and_audits`
- [x] 校验：PUT 非法 provider 前缀返回 400 -> `test_model_config_put_validates_provider`
- [x] 谓词：`is_valid_model_spec` 边界 -> `test_is_valid_model_spec`
- [x] UI：首页含「设置默认模型」控件 -> `test_index_has_model_config_controls`
- [x] 全量门禁通过

## 反例

- 基线 `fe11471`：无 `model-config` 端点（GET/PUT 均 404），`models` 无 `is_valid_model_spec`
  （`AttributeError`），首页无「设置默认模型」文案。

## 5 问威胁建模

1. **数据**：一个全局默认模型字符串，无敏感信息；provider 前缀受限集合。
2. **调用方**：控制台浏览器（经 Bearer token 鉴权）+ 角色映射。
3. **信任边界**：`model.read` 只放给 admin/operator，`model.write` 只放给 admin；跨租户不泄露
   （配置是平台级，无租户维度，GET 不返回租户私有信息）。
4. **恶意输入最坏结果**：非法 provider 前缀 → `is_valid_model_spec` 拒绝，400 且不落盘。
5. **失败是否泄露信息**：store 不可用返回 503 `model_config_unavailable`，不泄露底层细节。

## 范围外

- 多副本同步（ADR-0040 第二阶段）。
- `prove_it_works` 验收（SLICE-232）。
- 进程启动时读 store 初始化 override（由 prove_it_works 路径覆盖，本切片 GET 直接读 store）。

## 证据

- `docs/evidence/SLICE-231-model-config-endpoint.txt`
