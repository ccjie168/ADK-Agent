# SLICE-244 迁移模型面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第九步（面板迁移：Model 模型）

## 意图

把 legacy 内联壳的 Model（模型）面板的**只读摘要**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/ModelView.vue`：按 `auth.hasCapability("model.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/model`，渲染三张卡片。
2. 卡片与 legacy 等价：最近调用（`recent_calls`）、使用别名（`aliases` 逗号连接，空显示「—」）、
   降级次数（`fallbacks`）。
3. `web/src/router/index.ts`：`/model` 路由改用 `ModelView`。
4. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/model`（`model.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/model` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/ModelView.vue` 引用 `/api/model` 与 `model.read` -> `test_model_view_fetches_model`
- [ ] `/model` 路由使用 `ModelView` -> `test_model_route_uses_model_view`
- [ ] `ModelView.vue` 渲染 `recent_calls` 与 `fallbacks` -> `test_model_view_renders_fields`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-243 状态）：无 `ModelView`，`/model` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读模型调用摘要（最近调用数、别名、降级次数），无敏感载荷。
2. **调用方**：浏览器；`/api/model` 服务端已按 `model.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片只读，不含 model-config 写动作。
4. **恶意输入**：卡片字段只做文本插值渲染，无 `v-html`，无注入面。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- `/api/model-config` 默认模型读取与「设置默认模型」写动作（后续切片）。
- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-244-model-vue.txt`
