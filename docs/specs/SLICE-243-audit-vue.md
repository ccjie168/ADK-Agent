# SLICE-243 迁移审计面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第八步（面板迁移：Audit 审计）

## 意图

把 legacy 内联壳的 Audit（审计）面板迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/AuditView.vue`：按 `auth.hasCapability("audit.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/audit?limit=100`，按时间倒序渲染日志行。
2. 每行与 legacy 等价：`action target status latency_ms run_id(前 8 位) trace_id(前 8 位)`，
   `latency_ms` 空显示 `-`。
3. `web/src/router/index.ts`：`/audit` 路由改用 `AuditView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/audit`（`audit.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/audit` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/AuditView.vue` 引用 `/api/audit` 与 `audit.read` -> `test_audit_view_fetches_audit`
- [ ] `/audit` 路由使用 `AuditView` -> `test_audit_route_uses_audit_view`
- [ ] `AuditView.vue` 渲染 `trace_id` 与 `latency_ms` -> `test_audit_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-242 状态）：无 `AuditView`，`/audit` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读审计事件摘要（动作/目标/状态/延迟/run/trace），无敏感载荷。
2. **调用方**：浏览器；`/api/audit` 服务端已按 `audit.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含写动作。
4. **恶意输入**：日志行字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 审计过滤/分页/详情、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-243-audit-vue.txt`
