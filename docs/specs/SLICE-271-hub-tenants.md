# SLICE-271 Agent 中心：跨租户查看与评测报告下钻

状态: gated
依据: ADR-0041 阶段 2「注册数、lifecycle 分布、版本、评测、跨租户/远端目录」

## 意图

补齐阶段 2 剩下的两块：跨租户查看与评测下钻。

1. `AgentHubView.vue`：`admin` 身份显示租户切换输入框 + 「切换租户」按钮，
   调 `GET /api/registry?tenant=<tenant>`（留空即当前租户）；非 admin 不显示控件。
   查看其他租户时显示「正在查看租户 X」提示。
2. 每个 `has_eval_report` 为真的版本行显示「评测报告」按钮，
   `GET /api/registry/{tenant}/{id}/{version}/eval` 拉取报告并以 JSON 展示，可关闭。
   失败提示「评测报告不可用」（不泄露服务端错误体）。
3. 远端条目的 tenant 取条目自带的 `tenant` 字段，避免在跨租户视图下查错报告。

后端无改动（两个接口的 `?tenant=` 与租户校验均已存在）。

## 契约（先改）

无对外接口变化；`GET /api/registry?tenant=` 与 `GET /api/registry/{tenant}/{id}/{version}/eval`
已在 `docs/contracts/console.md` 记录。

## 完成判据

- [x] 视图含租户切换（`?tenant=`）且仅 admin 可见 -> `test_agent_hub_tenant_selector`
- [x] 视图可按版本拉取评测报告 -> `test_agent_hub_fetches_eval_report`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过
- [x] 实机验证：跨租户查询 403 语义与评测报告 200

## 反例

基线（SLICE-270 状态）：AgentHubView 只用固定 `/api/registry`，无租户切换、无评测按钮。上述用例失败。

## 5 问威胁建模

1. **数据**：manifest 元数据与评测报告（用例通过率等），非密钥。
2. **调用方**：浏览器；服务端对 `?tenant=` 非本租户且非 admin 返回 403，评测接口同样校验。
3. **信任边界**：服务端权威；前端只展示。
4. **恶意输入**：租户名经 `encodeURIComponent`；渲染无 `v-html`。
5. **失败是否泄露信息**：固定文案。

## 范围外

- 评测报告的可视化图表（表格/趋势）。
- 阶段 3 安全合规聚合。

## 证据

- `docs/evidence/SLICE-271-hub-tenants.txt`
