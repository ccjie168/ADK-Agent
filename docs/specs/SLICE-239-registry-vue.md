# SLICE-239 迁移注册表面板到 Vue

状态: gated
依据: ADR-0041 阶段 0 第四步（面板迁移：Registry / 市场）

## 意图

把 legacy 内联壳的 Registry（市场）面板的**只读列表 + 卡片徽标**迁到 Vue，行为等价（后端不动）：

1. 新增 `web/src/views/RegistryView.vue`：按 `auth.hasCapability("registry.read")` 决定是否拉取，
   用 `getJson` 调 `GET /api/registry`（无 tenant 参数时服务端取调用方租户），渲染卡片列表。
2. 每张卡片按 legacy 的 `registryCard` 等价渲染：头部 id（+ 版本或远端 label）、描述、徽标行
   （local：`local` + artifact 状态 + `eval`/`no eval` + lifecycle 状态；remote：`remote` + trust 状态 +
   可选 `disabled`）、元信息行（local：发布时间 + digest 前 12 位；remote：peer id）。
3. 徽标色调复用 legacy 的 `BADGE_TONES`（verified/published/eval/approved→good；untrusted/changed/retired/denied→bad；
   unsigned/unreachable/deprecated/expired→warn；cancelled→muted）。
4. `web/src/router/index.ts`：`/registry` 路由改用 `RegistryView`。
5. 重建 `web/dist/` 并提交。

后端无改动：`GET /api/registry`（`registry.read` 门控）已存在，见 `docs/contracts/console.md`。

## 契约（先改）

无对外接口变化。`GET /api/registry` 的返回形状已由既有契约覆盖，本切片只消费它。

## 完成判据

- [ ] `web/src/views/RegistryView.vue` 引用 `/api/registry` 与 `registry.read` -> `test_registry_view_fetches_registry`
- [ ] `/registry` 路由使用 `RegistryView` -> `test_registry_route_uses_registry_view`
- [ ] `RegistryView.vue` 含徽标色调（`untrusted`/`retired`） -> `test_registry_view_renders_badges`
- [ ] 前端可构建（`npm run build` 成功）且全量门禁通过

## 反例

基线（SLICE-238 状态）：无 `RegistryView`，`/registry` 路由用 `PlaceholderView`。三个用例在未改实现时全部失败。

## 5 问威胁建模

1. **数据**：只读注册表/远端目录摘要，无敏感载荷。
2. **调用方**：浏览器；`/api/registry` 服务端已按 `registry.read` 门控，前端 `hasCapability` 只是隐藏。
3. **信任边界**：SPA 只渲染；本切片不含 load/unload/open-chat 写动作，仅列表与徽标。
4. **恶意输入**：卡片字段只做文本渲染，无 `v-html`，digest/描述/状态都经插值转义。
5. **失败是否泄露信息**：无权限显示通用「无访问权限」，拉取失败显示通用不可用文案。

## 范围外

- 选中详情面板（manifest/artifact/eval JSON）、`/api/registry/load|unload` 与 Open chat（后续切片）。
- 其余面板迁移、前端单元测试框架（Vitest，属新 JS 依赖，另行评审）。

## 证据

- `docs/evidence/SLICE-239-registry-vue.txt`
