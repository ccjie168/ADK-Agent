# SLICE-281 新建 Agent 向导（`/agents/new`）

状态: gated
依据: ADR-0043（Accepted）第 4 节；ADR-0041 阶段 5（诉求 3）

## 意图

把 `POST /api/compose/preview` 与 `POST /api/compose` 做成页面向导：

1. **路由与入口**：`/agents/new`，导航「开发」组，入口文案「新建 Agent」；Agent 中心页加
   「新建」按钮（`registry.publish` 可见）。
2. **四步**：模板选择 → 参数表单 → 预览 → 发布。模板来自 `GET /api/compose/templates`
   （`registry.publish`）；`configured=false` 时显示「控制台未启用一键发布，请使用 CLI」并给可
   复制的等价 CLI 命令。
3. **参数表单**：`tenant` 默认取当前 principal 租户；`name`、`version`、`instruction` 必填，
   `owner`、`description` 可选；`tools` 按模板声明的工具做复选；`data_classes` 从
   `public/internal/confidential/restricted` 多选。前端按 `console.md` 的上限做即时校验
   （name 64、version/tenant 256、owner/description 2000、instruction 4000、tools/data_classes 各 16）。
4. **预览**：调用 preview，展示 manifest（格式化 JSON）、`agent.py` 源码与 `artifact_digest`；
   不改动注册表。预览要求 `registry.publish`。
5. **发布**：按钮要求 `registry.compose`；成功后显示版本与 digest，并提供「去注册表」链接。
   错误码映射固定文案：`compose_invalid`、`tenant_forbidden`、`compose_not_configured`、
   `registry_not_configured`、`registry_conflict`、`artifact_store_unavailable`、
   `registry_unavailable`、`forbidden`。
6. 无 `v-html`；不新增依赖；不上传任意源码或 ZIP。

## 契约（先改）

无后端接口变化；只消费 SLICE-280 的三个端点。`docs/contracts/console.md` 已描述请求/响应。

## 完成判据

- [ ] `/agents/new` 路由、导航入口与 Agent 中心「新建」按钮 -> `test_agent_wizard_route_and_nav`
- [ ] 读模板并渲染参数表单 -> `test_agent_wizard_reads_templates`
- [ ] 预览展示 manifest、源码与 digest -> `test_agent_wizard_previews_the_bundle`
- [ ] 发布按钮要求 `registry.compose` -> `test_agent_wizard_publish_requires_compose`
- [ ] 错误码映射到固定文案 -> `test_agent_wizard_maps_error_codes`
- [ ] 未配置密钥时显示 CLI 提示与可复制命令 -> `test_agent_wizard_shows_the_cli_hint`
- [ ] 前端校验上限与服务端一致 -> `test_agent_wizard_validates_limits`
- [ ] 无 `v-html`、无新依赖 -> `test_agent_wizard_uses_no_raw_html`
- [ ] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前没有 `/agents/new` 路由、视图与导航入口；上述用例在旧代码上失败。

## 5 问威胁建模

1. **数据**：模板参数、manifest 预览、生成的 `agent.py` 文本；不含密钥或宿主路径。
2. **调用方**：浏览器；服务端仍按 `registry.publish` / `registry.compose` 拦截，页面只决定展示。
3. **信任边界**：页面不持有签名密钥，发布由控制台服务端签名；页面不上传文件。
4. **恶意输入**：所有字段走 Vue 插值；前端校验只是体验，服务端仍全量校验；错误只显示固定文案。
5. **失败是否泄露信息**：未知错误统一「发布失败」；不渲染服务端错误体或异常文本。

## 范围外

- 任意源码上传、ZIP 导入、新模板。
- 密钥托管与轮换（运维手册）。
- 草稿保存与多模板。

## 证据

- `docs/evidence/SLICE-281-agent-wizard.txt`
- `docs/evidence/ui/SLICE-281-wizard-form.png`、`-preview.png`、`-published.png`
