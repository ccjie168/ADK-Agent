# SLICE-269 审批与工具授权决定按钮（ApprovalsView / GrantsView）

状态: draft
依据: 用户反馈「页面能力应在页面配置」；接口 `POST /api/approvals/{id}`（`approvals.decide`）与
`POST /api/tool-grants/{id}/decide`（`grants.decide`）均已存在

## 意图

1. `ApprovalsView.vue`：`approvals.decide` 下每行显示「批准」「拒绝」，页面顶部一个共享「决定理由」输入框；
   `POST /api/approvals/{request_id}`，body `{approved, reason}`；成功后刷新列表。
   错误码映射：`approval_not_found`、`approval_unavailable`、`tenant_forbidden`、`policy_denied`，其余回退状态码。
2. `GrantsView.vue`：`grants.decide` 下 `status === "pending"` 的行显示「批准」「拒绝」；
   `POST /api/tool-grants/{request_id}/decide`，body 同上。
   错误码映射：`grant_not_found`、`grant_already_decided`、`grant_expired`、`grant_store_unavailable`。
3. 所有请求 try/catch，网络失败提示「决定失败: 网络错误」；结果消息在表格上方。

后端无改动。

## 契约（先改）

无对外接口变化；两个端点已在 `docs/contracts/console.md` 记录。

## 完成判据

- [x] 审批面板按 `approvals.decide` 显示决定控件并提交 `approved` -> `test_approvals_view_decides`
- [x] 授权面板按 `grants.decide` 显示决定控件并调用 `/decide` -> `test_grants_view_decides`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过
- [x] 实机验证：批准一条演示审批

## 反例

基线（SLICE-268 状态）：两个面板只读表格，无决定控件。上述用例失败。

## 5 问威胁建模

1. **数据**：审批/授权决定与理由文本。
2. **调用方**：浏览器；服务端按 `approvals.decide`/`grants.decide` 强制，审批另有 RBAC `approval.decide` 策略与租户检查。
3. **信任边界**：服务端权威；`approved` 必须是布尔，理由必须是字符串，否则 400；两个决定都写审计。
4. **恶意输入**：理由只作文本回传，服务端校验类型；渲染无 `v-html`。
5. **失败是否泄露信息**：固定文案或状态码。

## 范围外

- 审批历史/详情视图、授权申请表单、批量决定。
- 对端与远端目录表单（下一个切片）。

## 证据

- `docs/evidence/SLICE-269-decide-buttons.txt`
