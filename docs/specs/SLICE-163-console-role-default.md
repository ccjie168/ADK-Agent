# SLICE-163 控制台角色默认收紧到 requester

状态: gated
依据: ADR-0030（Accepted 2026-11-19）与 `docs/review/m6-enterprise-trust-chain.md` 的 Gate 1：
生产角色不得来自用户可控的运行参数。`--role` 缺省不再 admin，改为最低权限 requester。

## 意图

1. `build_console_app` 的 `roles` 缺省从 `["admin"]` 改为 `["requester"]`
   （`src/adk_agent/console.py:2619`）。
2. `--role` 帮助文本与契约默认说明从 admin 改为 requester。
3. bearer / 静态 token 模式不再静默授予 admin；admin 能力必须显式 `--role admin` 或由
   OIDC claim 映射（`identity/oidc.py` 已有 `roles_claim`，本次不改）。
4. `_capabilities_for(["requester"])` 落到 BASE（现有逻辑已如此，`console.py:191`）。

## 契约（先改）

- `docs/contracts/cli.md` 的 `--role` 默认说明。

## 完成判据

- [x] 无 `--role` 时 `/api/me` 返回 roles `["requester"]`、capabilities == BASE -> `test_default_role_is_requester`
- [x] 无 `--role` 时主体不含 admin、不获得 `registry.load` -> `test_default_role_is_not_admin`
- [x] 显式 `--role admin` 仍返回全部能力 -> `test_admin_gets_every_capability`
- [x] 全量门禁通过

## 反例

- [x] 基线 `/api/me` 无 `--role` 返回 admin 与全部能力（实现前跑红）

## 5 问威胁建模

1. **数据**：控制台 principal 的角色与能力清单。
2. **调用方**：bearer / 静态 token 持有者、OIDC 主体。
3. **信任边界**：运行时 `--role` 参数到控制台 RBAC 能力派生。
4. **恶意输入最坏结果**：无 `--role` 的部署静默获得 admin，可写凭据、注册表、对端与授权
   （缓解：默认 requester，admin 必须显式声明或经 OIDC claim）。
5. **失败是否泄露信息**：固定 403 `forbidden`，不因角色缺失泄露对象存在性。

## 范围外

- OIDC claim → 角色映射（`identity/oidc.py` 已实现，本次不动）。
- 能力表 `_CAPABILITIES_*` 去硬编码为 policy 驱动（ADR-0030 后续切片）。
- `deploy/k8s/multi-replica.yaml` 的 `--role admin` 移除（清单显式声明，不违反默认收紧；
  ADR-0030 后续切片）。
- `--role` 在非回环 + 无 OIDC 场景的禁用（后续切片）。

## 证据

- `docs/evidence/SLICE-163-console-role-default.txt`
