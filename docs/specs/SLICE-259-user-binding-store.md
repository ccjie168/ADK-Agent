# SLICE-259 用户绑定 store（subject → 角色，租户维度）

状态: gated
依据: ADR-0041 阶段 1 第 3 节「角色/授权模型」（用户绑定 = subject → 一个或多个角色）

## 意图

在 SLICE-258 的角色定义 store 之上，加用户绑定 store：一个用户（`(tenant, subject)`）绑定到一个或多个角色。
本切片**只加 store 与校验，不接线到能力解析**（运行时化是 SLICE-260）。

1. `core/user_bindings.py` 新增 `UserBinding`（tenant + subject + roles）、`UserBindingStore` 端口错误
   （`UserBindingConflict`/`UserBindingNotFound`/`UserBindingStoreError`/`UserBindingStoreUnavailable`）。
   `tenant` 走 `_SAFE_NAME` 白名单；`subject` 只限非空/≤256（OIDC `sub` 可能是 UUID/邮箱/带分隔符），
   roles 每项须为合法角色名（与 `RoleDefinition.name` 同款白名单），去重排序。
2. `core/ports.py` 新增 `UserBindingStore` Protocol（add/get/list/delete）。
3. `registry/user_bindings.py` 新增 `FileUserBindingStore`：目录按 `safe_join(root, tenant)`，
   文件名用 `sha256(subject)` 十六进制（subject 任意安全），JSON 内容存完整 `(tenant, subject, roles)`。
4. `registry/user_bindings_postgres.py` 新增 `PostgresUserBindingStore`：`adk_user_bindings`
   `(tenant, subject, definition jsonb, updated_at)`，主键 `(tenant, subject)`，幂等 insert-then-compare。
5. `core/__init__.py` 导出新类型。

后端对外接口无变化（`/api/*` 不动），用户绑定尚未被能力解析消费。

## 契约（先改）

无对外接口变化。用户绑定 store 是本切片新增的内部持久化，`docs/contracts/` 不需改动。

## 完成判据

- [x] `UserBinding` 归一化 roles 且拒绝非法 tenant / 非法角色 -> `test_user_binding_normalizes_roles`、`test_user_binding_rejects_invalid_tenant`、`test_user_binding_rejects_invalid_role`
- [x] 文件 store 增/查/列/删、租户隔离、冲突 -> `test_file_user_binding_store_roundtrip`、`test_file_user_binding_store_conflict`
- [x] 任意 subject（含路径分隔符等）安全落盘 -> `test_file_user_binding_subject_is_path_safe`
- [x] `--full` 门禁通过

## 反例

基线（SLICE-258 状态）：无 `core/user_bindings.py` / `registry/user_bindings.py` / `registry/user_bindings_postgres.py`。
上述用例在未改实现时全部失败（ImportError 或断言失败）。

## 5 问威胁建模

1. **数据**：绑定只含 `(tenant, subject) → 角色名集合`，无密钥、无 PII（subject 可能是邮箱，但属配置元数据）。
2. **调用方**：本切片无网络面；store 只被测试与后续切片的服务端代码调用。
3. **信任边界**：文件 store 的 `tenant` 经 `safe_join` 白名单，`subject` 用 sha256 命名文件，
   避免路径穿越/任意文件名写入；Postgres 主键 `(tenant, subject)`。
4. **恶意输入**：`UserBinding` 用 pydantic 校验（tenant/roles 白名单、subject 长度上限、roles 去重排序），
   非法记录读写时 fail-closed。
5. **失败是否泄露信息**：store 错误按现有错误类映射，不泄露记录内容。

## 范围外

- 能力解析运行时化（`_capabilities_for` 读 role store + 用户绑定）、`--role-store`/`--user-binding-store` CLI 接线（后续切片）。
- 管理面板与 `/api/roles`/`/api/users`、写审计（后续切片）。
- 绑定是否校验角色在 role store 中存在（跨 store 校验，留到运行时化/管理切片）。

## 证据

- `docs/evidence/SLICE-259-user-binding-store.txt`
