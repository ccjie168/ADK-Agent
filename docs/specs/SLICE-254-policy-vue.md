# SLICE-254 迁移策略面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十九步（面板迁移：Policy 策略）

## 意图

把 legacy 内联壳的 Policy（策略）面板的**只读视图**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/PolicyView.vue`：按 `auth.hasCapability("policy.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/policy`，展示策略 JSON（`version` 与 `bindings`）。
2. `web/src/router/index.ts`：新增 `/policy` 路由用 `PolicyView`。
3. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/policy`（`policy.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/policy` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/PolicyView.vue` 引用 `/api/policy` 与 `policy.read` -> `test_policy_view_fetches_policy`
- [ ] `/policy` 路由使用 `PolicyView` -> `test_policy_route_uses_policy_view`
- [ ] `PolicyView.vue` 渲染 `version` 与 `bindings` -> `test_policy_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-253 状态）：无 `PolicyView`，路由无 `/policy`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读策略定义（版本 + 角色绑定），无敏感载荷。
2. **调用方**：浏览器；`/api/policy` 服务端已按 `policy.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 save（PUT）写动作。
4. **恶意输入**：策略 JSON 只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- save（PUT `/api/policy`）写动作（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-254-policy-vue.txt`
