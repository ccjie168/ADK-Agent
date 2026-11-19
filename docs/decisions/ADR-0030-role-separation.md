# ADR-0030 角色与职责分离：去掉 admin 默认角色

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

`cli.py:1436` 的 `--role` 默认 `admin`，bearer 模式下控制台主体直接获得该角色。角色本身是自由
字符串，能力集在 `console.py` 的 `_CAPABILITIES_*` 里按角色硬编码；`RolePolicyEngine`
（`rbac.py:13`）只做通配匹配。风险：任何 token 持有者默认为 admin，且「谁定义策略」与「谁执行
高风险写」没有分离。这比「要不要 Planner」更优先。

## 决定

1. **冻结 5 个平台角色**：`admin`（平台）、`operator`（运行）、`developer`（Agent 开发）、
   `auditor`（只读审计）、`requester`（业务用户）。业务角色后置。
2. **去掉 `--role admin` 默认。** bearer 模式不再静默授予 admin；角色映射必须显式来自 OIDC
   claim（AD 组 → 角色）或显式 allowlist，否则主体为最低权限 `requester`。
3. **角色 → 能力映射改为数据驱动。** 能力集由 `AccessPolicy` 从角色推导，不再在 `console.py`
   里按角色硬编码 `_CAPABILITIES_*`。
4. **职责分离。** 定义策略的角色不能无审批执行高风险写；admin 不能审批自己发起的 L4 动作
   （L4 需双人）。
5. **审计记录授权该动作的角色/能力**（已有 `policy_version`，扩展到角色）。

## 备选与否决

- **保留 `--role admin` 默认 + 文档提醒**：默认不安全，违反最小权限；否决。
- **每个业务部门各建角色**：MVP 期过度；先平台角色，业务角色用 principal attributes 表达。

## 后果

- OIDC claim 映射需文档化（`docs/guides/ad-oidc.md` 补 AD 组 → 角色）。
- `console.py` 能力映射重构为 policy 驱动，删除 `_CAPABILITIES_*` 硬编码。
- 部署清单必须显式声明角色，`deploy/k8s/multi-replica.yaml` 的 `--role admin` 移除。
- 现存测试依赖 admin 默认的需按新映射更新（不修改断言，调整夹具角色来源）。

## 切片（待确认后分配）

1. 角色/能力数据模型与 `AccessPolicy` 派生。
2. `--role` 默认改最低权限 + OIDC claim 映射文档。
3. `console.py` 能力映射去硬编码 + 职责分离规则。
4. 部署清单与契约更新。
