# SLICE-267 注册表动作与清单注册（RegistryView）

状态: draft
依据: 用户反馈「注册这类页面能力应在页面配置」；接口 `POST /api/registry/load|unload`（`registry.load`）
与 `POST /api/import/agent`（`registry.publish`）均已存在

## 意图

RegistryView 从只读卡片变成可操作：

1. 每张本地卡片（`source !== "remote"` 且有版本）加「加载」「卸载」按钮，按 `registry.load` 显示：
   - 加载 → `POST /api/registry/load`，body `{tenant, id, version}`；409 提示「名称冲突：请先卸载同名 Agent」。
   - 卸载 → `POST /api/registry/unload`，body `{name}`（即 agent id）。
2. 面板底部加「注册 Agent 清单」：JSON 文本域（`registry.publish` 下显示）+ 注册按钮，
   本地 `JSON.parse` 预检后 `POST /api/import/agent`；成功显示 `id@version` 并刷新列表；
   400 提示「清单无效」，403 提示「租户不允许」。
3. 所有请求走 `post()` 包装，网络失败提示「请求失败: 网络错误」，不留未处理的 Promise。
4. 结果消息显示在面板顶部。

后端无改动；带签名**工件**的发布仍走 CLI（私钥不进浏览器），页面上是 manifest 注册。

## 契约（先改）

无对外接口变化；三个端点已在 `docs/contracts/console.md` 记录。

## 完成判据

- [x] 视图提供加载与卸载（`/api/registry/load|unload`，`registry.load`） -> `test_registry_view_loads_and_unloads`
- [x] 视图提供清单注册（`/api/import/agent`，`registry.publish`，本地 JSON 预检） -> `test_registry_view_registers_manifest`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过
- [x] 实机验证：加载/卸载/注册各一次

## 反例

基线（SLICE-266 状态）：RegistryView 只 GET `/api/registry` 渲染卡片，无任何写控件。上述用例失败。

## 5 问威胁建模

1. **数据**：manifest 元数据与加载动作；无密钥。
2. **调用方**：浏览器；服务端按 `registry.load`/`registry.publish` 强制，加载还校验租户与工件信任。
3. **信任边界**：服务端权威（`published_from`、签名/工件校验、`agent.load`/`agent.unload`/`agent.import` 审计）。
4. **恶意输入**：清单经服务端 `AgentManifest` 校验；前端只做 JSON 语法预检；渲染无 `v-html`。
5. **失败是否泄露信息**：固定文案或状态码。

## 范围外

- 带签名工件上传/发布（需私钥，保留 CLI）。
- 远端目录注册/刷新/禁用（下一批：对端与远端目录）。
- 连接器/凭据、审批与工具授权决定按钮。

## 证据

- `docs/evidence/SLICE-267-registry-actions.txt`
