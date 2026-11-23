# SLICE-249 迁移凭据面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第十四步（面板迁移：Credentials 凭据）

## 意图

把 legacy 内联壳的 Credentials（凭据）面板的**只读列表**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/CredentialsView.vue`：按 `auth.hasCapability("connectors.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/credentials`，渲染表格。
2. 表格列与 legacy 等价：凭据 ID（`credential_id`）、租户（`tenant`）、secret 引用（`secret_ref`）、
   描述（`description`）、启用（`enabled` → enabled/disabled）。响应已由服务端排除 `wrapped_secret`。
3. `web/src/router/index.ts`：新增 `/credentials` 路由用 `CredentialsView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/credentials`（`connectors.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/credentials` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/CredentialsView.vue` 引用 `/api/credentials` 与 `connectors.read` -> `test_credentials_view_fetches_credentials`
- [ ] `/credentials` 路由使用 `CredentialsView` -> `test_credentials_route_uses_credentials_view`
- [ ] `CredentialsView.vue` 渲染 `credential_id` 与 `secret_ref` -> `test_credentials_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-248 状态）：无 `CredentialsView`，路由无 `/credentials`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读凭据绑定元数据（id/租户/secret 引用/描述/启用），服务端已排除密文。
2. **调用方**：浏览器；`/api/credentials` 服务端已按 `connectors.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 register/disable 写动作。
4. **恶意输入**：单元格字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- register/disable 写动作（后续切片）、其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-249-credentials-vue.txt`
