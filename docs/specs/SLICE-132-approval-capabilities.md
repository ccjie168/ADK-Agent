# SLICE-132 审批接口的能力校验

状态: gated
依据: ADR-0022 第 1、8 条。控制台按能力隐藏审批面板，但服务端只做了租户隔离；发布者角色能直接调接口读取与决定审批。本切片补上服务端检查。

## 意图（要什么，不写怎么写）

1. `GET /api/approvals` 与 `GET /api/approvals/history` 需要 `approvals.read`。
2. `POST /api/approvals/{request_id}` 需要 `approvals.decide`。
3. 缺少能力返回 403 `{"error": "forbidden"}`；租户隔离与 admin 语义保持不变。
4. 现有 `operator` 与 `admin` 角色行为不变；没有匹配角色的主体按基础能力处理，不能读写审批。
5. 其他控制台接口的能力缺口不在本切片，单列后续审查。

## 数据形状

- 复用 `console._capabilities_for(roles)`，不新增契约类型。
- 三个路由在 `_principal_for(request)` 之后立即检查能力，先于任何存储读取或写入。

## 契约（先改）

- `docs/contracts/console.md`：审批列表、决定与历史三处写明所需能力与 403。

## 新增/修改文件

- 修改 `src/adk_agent/console.py`
- 修改 `tests/test_console_approvals.py`、`tests/test_console_approvals_history.py`、`tests/test_console_approvals_expiry.py`（调用主体补角色，断言不变）
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-132-approval-capabilities.txt`

## 完成判据（可执行）

- [x] 发布者读审批列表 403 `forbidden` -> `tests/test_console_approvals.py::test_roles_without_approval_capabilities_are_forbidden`
- [x] 发布者决定审批 403 且审批仍待决 -> 同上
- [x] 发布者读审批历史 403 -> 同上
- [x] operator 与 admin 的列表、决定、历史行为不变 -> 既有审批用例
- [x] 租户过滤不变 -> `::test_list_pending_filters_by_tenant` 与 history 的租户用例
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：发布者能读审批列表 -> 期望 `::test_roles_without_approval_capabilities_are_forbidden` 失败
  （实现前已在演示实例上实测：发布者 `GET /api/approvals` 返回 200）

## 5 问威胁建模（10 分钟）

1. **数据**：待决与历史审批、审批决定、租户与主体角色。
2. **调用方**：控制台会话（静态 token 或 OIDC）。
3. **信任边界**：前端能力清单到服务端授权。
4. **恶意输入最坏结果**：越权读取审批内容（缓解：`approvals.read`）；越权批准或拒绝副作用（缓解：`approvals.decide`）；跨租户（缓解：租户隔离保持不变）；前端绕过（缓解：服务端检查，界面隐藏不再承担授权）。
5. **失败是否泄露信息**：403 只回 `forbidden`，不透露审批是否存在。

## 范围外

- 其他控制台接口（审计、连接器、凭据、注册表发布等）的能力审查。
- 站内角色分配与租户开通。
- 审批通知与过期策略。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-132-approval-capabilities.txt`
