# SLICE-260 能力解析运行时化（角色 store 驱动，fail-closed）

状态: gated
依据: ADR-0041 阶段 1 第 3 节「能力解析」与「安全边界」

## 意图

让 `_capabilities_for` 从「硬编码角色表」改为「读角色定义 store 的角色名 → 能力并集」：

1. `console.py` 的 `_capabilities_for(roles)` 保持为纯函数（无 store 时的向后兼容路径）。
   新增 `async def _caps_for(caller)`：当 `role_store is None` 时返回 `_capabilities_for(caller.roles)`，
   行为与现在完全一致；配置了 store 时按 `caller.roles` 逐个查 store，取能力并集。
2. 未在 store 中定义的角色贡献空集；并集为空时回落 `CAPABILITIES_BASE`（ADR「未定义角色回落基础能力」）。
3. **fail-closed**：store 读失败（`RoleStoreError`）时记日志并返回 `CAPABILITIES_BASE`，不放行任何
   超出基础的权限，`admin` 也一并失去管理权限（ADR 安全边界明确要求这个方向）。
4. `_forbidden_if_missing` 改为 async（`await` 查 `_caps_for`），全部调用点加 `await`；
   `/api/me` 的 `capabilities`、`/api/overview` 的 `caps` 与审批三处直连判断改用 `_caps_for`。
5. CLI：`console` 新增 `--role-store-dir` / `--role-store-db`（env `ROLE_DATABASE_URL`），
   语义与 `--credentials-dir`/`--credential-db` 一致（同设报错、env 冲突报错）。配置 store 时，
   启动即把 `seed_builtin_roles()` 幂等写入 store，保证内置角色（含 admin）开箱可用。
6. `build_console_app` / `run_console` 新增 `role_store` 参数。

用户绑定（`--user-binding-store`）并入角色集是 SLICE-261，本切片不读绑定。

## 契约（先改）

`docs/contracts/console.md` 补一节「能力解析」：说明 `capabilities` 的来源优先级
（token 角色 → role store 定义 → 基础能力回落）、store 读失败时 fail-closed 到基础能力，
以及 `--role-store-dir`/`--role-store-db` 的存在。外部接口形状不变。

## 完成判据

- [x] 未配置 store 时 admin/operator/requester 的能力集合与改动前逐项相同 -> `test_capabilities_unchanged_without_store`
- [x] 配置 store 后，store 中自定义角色生效 -> `test_role_store_definitions_grant_capabilities`
- [x] store 中未定义的角色只得到基础能力 -> `test_undefined_role_falls_back_to_base`
- [x] store 读失败时 fail-closed 到基础能力（admin 不例外） -> `test_role_store_failure_fails_closed`
- [x] 启动种子使内置 admin 在空 store 上仍可管理 -> `test_seed_builtin_roles_keeps_admin_working`
- [x] `--role-store-dir` 与 `--role-store-db` 同设退出 2 -> `test_console_rejects_two_role_stores`
- [x] `--full` 门禁通过，且 `scripts/prove_it_works.py` 权限语义无回归

## 反例

基线（SLICE-259 状态）：`build_console_app` 不接受 `role_store`，`_caps_for` 不存在，
CLI 无 `--role-store-dir`。上述用例在未改实现时全部失败（TypeError / ImportError / argparse 退出码不符）。

## 5 问威胁建模

1. **数据**：能力集合决定谁能调哪个面板接口；不涉及密钥。
2. **调用方**：任何携带 bearer/OIDC token 的浏览器；dev 模式为 `--role`。
3. **信任边界**：能力解析在服务端每个受保护路由前执行；前端 `hasCapability` 只影响渲染。
   角色定义来自运维配置的 store，不经请求体。
4. **恶意输入**：请求方无法影响自己的角色（来自 token claim）或 store 内容；改 store 需要管理面（SLICE-262）。
5. **失败是否泄露信息**：store 失败只记类型级日志并降级为基础能力，不返回 store 内容；403 响应体仍是固定 `forbidden`。

## 风险与回滚

这是阶段 1 唯一改动后端授权行为的切片。风险点是「配置 store 后忘记种子」导致 admin 掉权限 →
用启动种子 + `test_seed_builtin_roles_keeps_admin_working` 覆盖。回滚方式：不传 `--role-store-*`
即回到硬编码行为（`test_capabilities_unchanged_without_store` 保证等价）。

## 范围外

- 用户绑定并入角色集（SLICE-261）、`/api/roles`、`/api/users`、管理面板与 `role.define`/`user.bind` 审计（SLICE-262）。
- 角色定义的租户维度。

## 证据

- `docs/evidence/SLICE-260-capabilities-runtime.txt`
