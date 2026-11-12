# SLICE-029 RBAC 与策略管理界面（M4-2）

状态: gated
依据: ADR-0002 第 5、6 条

## 意图（要什么，不写怎么写）

补齐 M4 的第二条。

- 访问策略是数据：版本加角色绑定，绑定带租户。
- 决定顺序：先看拒绝，再看允许，默认拒绝。
- 绑定只对同一租户生效，跨租户不匹配。
- 角色来自 `Principal.roles`。控制台用 `--role` 指定。
- 策略引擎是 `PolicyEngine` 的实现，可替换。
- 策略文件用 JSON，原子写入。
- 控制台提供策略查看和替换接口，替换写审计。
- 控制台聊天按 `agent.run` 做策略检查，拒绝返回 403。
- 控制台页面有策略面板。
- 这一刀不做 OIDC 角色映射，也不做多控制台用户。

## 新增文件

- `src/adk_agent/core/rbac.py`
- `src/adk_agent/rbac.py`
- `tests/test_rbac.py`
- `tests/test_policy_api.py`
- `docs/contracts/access_policy.schema.json`
- `docs/evidence/SLICE-029-rbac-policy-ui.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`：导出 `AccessPolicy`、`RoleBinding`
- `src/adk_agent/console.py`：策略接口、聊天策略检查、策略面板
- `src/adk_agent/cli.py`：`console --policy`、`console --role`
- `scripts/export_contracts.py`：导出 `access_policy.schema.json`
- `docs/contracts/cli.md`：新增参数
- `docs/specs/ROADMAP.md`：M4 进度

## 完成判据（可执行）

- [x] 角色允许动作 -> `tests/test_rbac.py::test_role_allows_action`
- [x] 没有绑定的角色默认拒绝 -> `tests/test_rbac.py::test_unknown_role_is_denied`
- [x] 拒绝优先于允许 -> `tests/test_rbac.py::test_deny_overrides_allow`
- [x] 绑定按租户隔离 -> `tests/test_rbac.py::test_binding_is_tenant_scoped`
- [x] 动作通配符覆盖所有目标 -> `tests/test_rbac.py::test_wildcard_action_allows_all_targets`
- [x] 策略可热替换 -> `tests/test_rbac.py::test_update_swaps_policy`
- [x] 策略文件往返 -> `tests/test_rbac.py::test_file_store_roundtrip`
- [x] 非法策略被拒绝 -> `tests/test_rbac.py::test_invalid_policy_rejected`
- [x] GET 策略 -> `tests/test_policy_api.py::test_get_policy`
- [x] PUT 策略落盘并审计 -> `tests/test_policy_api.py::test_put_policy_persists_and_audits`
- [x] 非法 PUT 不改旧策略 -> `tests/test_policy_api.py::test_put_invalid_policy_keeps_old`
- [x] 无 `policy.update` 权限不能改策略 -> `tests/test_policy_api.py::test_put_policy_denied_without_role`
- [x] 未配置策略文件时接口不存在 -> `tests/test_policy_api.py::test_policy_endpoints_absent_without_policy_file`
- [x] 聊天拒绝无权限角色 -> `tests/test_policy_api.py::test_chat_denied_without_role`
- [x] 聊天放行有权限角色 -> `tests/test_policy_api.py::test_chat_allowed_with_role`
- [x] 页面有策略面板 -> `tests/test_policy_api.py::test_index_has_policy_panel`
- [x] 契约 schema 同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.rbac import RolePolicyEngine` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.core import AccessPolicy` -> 当前 `ImportError`
- [x] 反例 3：控制台不接受 `policy_file` 参数 -> 当前 `TypeError`
- [x] 反例 4：策略拒绝时聊天仍然执行 -> 期望 403 且运行次数为 0
- [x] 反例 5：非法 PUT 覆盖旧策略 -> 期望 400 且旧文件不变
- [x] 反例 6：无权限角色 PUT 策略 -> 期望 403 且文件不变（防止自提权）

## 契约

```python
class RoleBinding(BaseModel):
    role: str
    tenant: str
    allow: list[str] = []   # "action:target"，target 可用 "*"
    deny: list[str] = []

class AccessPolicy(BaseModel):
    version: str
    bindings: list[RoleBinding] = []
```

- `role`、`tenant` 匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*$`。
- 权限串格式是 `<action>:<target>`。`*` 匹配任意动作或目标。
- 绑定只在 `binding.tenant == principal.tenant` 且 `binding.role in principal.roles` 时生效。
- 任意生效绑定的 `deny` 命中即拒绝。没有 allow 命中则拒绝。
- `PolicyDecision.policy_version` 是 `rbac:<policy.version>`。
- 控制台 `GET /api/policy` 返回策略 JSON。未配置策略文件时返回 404。
- 控制台 `PUT /api/policy` 先校验格式，再按当前策略检查 `policy.update:<新版本>`。
- 无权限返回 403 `policy_denied`，不写文件，不替换。防止自提权。
- 校验后原子写文件、热替换、写 `policy.update` 审计，返回新策略。
- 非法 PUT 返回 400，不写文件，不替换。
- 控制台聊天在调用 runtime 前检查 `agent.run:<agent>`。拒绝返回 403，并写 `agent.run` `denied` 审计。
- 控制台 principal 的角色来自 `--role`，默认 `admin`。

## 5 问威胁建模（10 分钟）

1. **数据**：角色、租户、权限串、策略版本、控制台 token。
2. **调用方**：控制台、CLI、后续网关联邦身份。
3. **信任边界**：策略文件、控制台 token、调用方传入的角色。
4. **恶意输入最坏结果**：自封角色拿到全权限；跨租户读策略；策略文件被半写导致放行或拒绝错乱；非法策略替换旧策略；通过聊天绕过策略。用角色来自服务端配置而非请求、绑定租户过滤、原子写和先校验后替换、调用前检查处理。
5. **失败是否泄露信息**：拒绝只返回 `policy_denied`，不透露哪条绑定缺失。审计只存动作和目标。

### 已知边界

- 控制台是单 token 单身份。角色来自启动参数，没有 OIDC 角色映射。
- 策略管理没有变更历史，只有审计事件。
- 策略版本由人维护，不强制递增。
- RBAC 只覆盖控制台聊天入口。工具网关和编排策略仍用各自的 grant 引擎。
- 未配置 `--policy` 时控制台不做 RBAC，保持旧行为。

## 证据

- 反例红: `ImportError: cannot import name 'AccessPolicy' from 'adk_agent.core'`
- 实现后绿: RBAC 与策略接口测试 16 passed
- 真实控制台: 聊天和策略写入都按角色拒绝，审计有两条 denied
- `check.py --fast` -> 272 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 272 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-029-rbac-policy-ui.txt`
