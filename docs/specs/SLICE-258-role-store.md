# SLICE-258 角色定义 store（角色 → 能力集合的持久化基础）

状态: gated
依据: ADR-0041 阶段 1 第 3 节「角色/授权模型」（已确认第 5 条）

## 意图

把控制台的角色→能力模型从「`console.py` 内硬编码常量」抽成可持久化的角色定义 store，作为阶段 1
运行时化的地基。本切片**只加 store 与种子，不改能力解析**（`_capabilities_for` 仍走硬编码映射，行为不变）。

1. 把能力常量 `_CAPABILITIES_ALL/BASE/OPERATOR/PUBLISHER` 从 `console.py` 迁到 `core/roles.py`
   并公开为 `CAPABILITIES_*`，`console.py` 改为从 `.core` 导入（纯搬移，值不变）。
2. `core/roles.py` 新增 `RoleDefinition`（name + capabilities + builtin + description）、
   `RoleStore` 端口错误（`RoleConflict`/`RoleNotFound`/`RoleStoreError`/`RoleStoreUnavailable`）、
   `BUILTIN_ROLES` 种子表与 `seed_builtin_roles()`（7 个内置角色：admin/operator/ops/approver/
   publisher/developer/base，能力集合与现网 `_CAPABILITIES_*` 一致）。
3. `core/ports.py` 新增 `RoleStore` Protocol（add/get/list/delete）。
4. `registry/roles.py` 新增 `FileRoleStore`：按角色名一个 `<name>.json`（全局、无租户维度），
   原子写（temp + `os.link`），复用 `safe_join`。
5. `registry/roles_postgres.py` 新增 `PostgresRoleStore`：`adk_roles(name PK, definition jsonb,
   updated_at)`，幂等 insert-then-compare（复用 `LazyPool`）。
6. `core/__init__.py` 导出新类型与常量。

后端对外接口无变化（`/api/*` 不动）；角色 store 尚未接线到控制台，`--full` 门禁应全绿且
`prove_it_works` 权限语义不回退。

## 契约（先改）

无对外接口变化。角色 store 是本切片新增的内部持久化，`docs/contracts/` 不需改动。

## 完成判据

- [x] `RoleDefinition` 归一化能力（去重 + 排序）且拒绝非法 name -> `test_role_definition_normalizes_capabilities`、`test_role_definition_rejects_invalid_name`
- [x] 文件 store 增/查/列/删与冲突 -> `test_file_role_store_roundtrip`、`test_file_role_store_conflict`
- [x] 内置种子与能力常量一致 -> `test_seed_builtin_roles_match_capabilities`
- [x] 能力常量已移出 `console.py` -> `test_capabilities_moved_out_of_console`
- [x] `--full` 门禁通过（`prove_it_works` 权限语义不回退）

## 反例

基线（SLICE-257 状态）：无 `core/roles.py` / `registry/roles.py` / `registry/roles_postgres.py`，
`console.py` 仍内联 `_CAPABILITIES_*`。上述用例在未改实现时全部失败（ImportError 或断言失败）。

## 5 问威胁建模

1. **数据**：角色定义只含「角色名 → 能力名集合」的元数据，无密钥、无 PII。
2. **调用方**：本切片无网络面；store 只被测试与后续切片的服务端代码调用。
3. **信任边界**：文件/Postgres store 沿用 credentials 的 `safe_join` + 原子写 + `LazyPool` 模式，
   角色名经 `_SAFE_NAME` 白名单。
4. **恶意输入**：`RoleDefinition` 用 pydantic 校验（name 白名单、能力为字符串、去重排序），
   非法记录读写时 fail-closed。
5. **失败是否泄露信息**：store 错误按现有错误类映射，不泄露记录内容。

## 范围外

- 能力解析运行时化（`_capabilities_for` 读 store）、`--role-store` CLI 接线（下一切片）。
- 用户绑定 store、管理面板与 `/api/roles`/`/api/users`、写审计（后续切片）。
- 内置角色不可变的强制、租户维度角色（阶段 1 后续再定）。

## 证据

- `docs/evidence/SLICE-258-role-store.txt`
