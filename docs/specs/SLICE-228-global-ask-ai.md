# SLICE-228 全局 Ask AI

状态: gated
依据: ADR-0039 MVP 第 7 项（全局 Ask AI：确定性语义路由展示 + 深链）

## 意图

1. 新增全局 Ask AI 入口 `section#ask-ai`（导航「总览」组），顶栏可随时输入自然语言需求。
2. 新增 `POST /api/ask-ai`：输入需求文本，自动取第一个术语表，用 `route_request` 做确定性
   路由回放（`bindings` 随请求传入），返回命中的 `RoutedCapability` 列表与 `scheme_id`。
3. 命中的能力/工具展示在 Ask AI 面板，`tool_id` 深链到 Tools 面板。

## 契约（先改）

- `docs/contracts/console.md` 补 `POST /api/ask-ai` 一节。

## 完成判据

- [x] 首页含 Ask AI 面板 -> `test_index_has_ask_ai_panel`
- [x] Ask AI 端点返回命中 -> `test_ask_ai_endpoint_returns_hits`
- [x] 全量门禁通过

## 反例

- 基线 `2bc1fa2`：首页没有 `id="ask-ai"`，没有 `/api/ask-ai` 路由，两个用例分别失败（404）。

## 5 问威胁建模

1. **数据**：需求文本、命中的概念与能力绑定、scheme_id。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 租户 → 可见的术语表与路由命中。
4. **恶意输入最坏结果**：构造文本触发大量标签命中。缓解：只做确定性标签匹配，返回命中与标签，
   不执行工具；工具真正执行前的授权仍由既有工具网关/审批把关。
5. **失败是否泄露信息**：无术语表返回空命中；存储不可用返回 `terminology_unavailable`。

## 范围外

- 完整多 agent 编排（计划结构选择的模型填空属 ADR-0038 第二阶段）。
- 能力绑定的持久化 store（bindings 由调用方随请求传入，另开切片）。
- 命中的自动执行/触发（MVP 只展示 + 深链）。

## 证据

- `docs/evidence/SLICE-228-global-ask-ai.txt`
