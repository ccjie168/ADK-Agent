# SLICE-226 语义层面板

状态: gated
依据: ADR-0039 MVP 第 5 项（语义层面板：术语表、概念、能力绑定、路由回放）

## 意图

1. 控制台接入语义层存储 `ConceptSchemeStore`（文件 / Postgres 双后端），新增参数
   `terminology`，CLI 加 `--terminology-dir` / `--terminology-db`。
2. 新增 `GET /api/semantics`：列出当前租户的术语表（概念、标签、映射）。
3. 新增 `POST /api/semantics/route`：输入需求文本，用 `route_request` 回放确定性路由，
   返回命中的 `RoutedCapability` 列表（需求 → 概念 → 能力 → 工具）。
4. 新增语义层面板 `section#semantics`（导航「数据」组），展示术语表与路由回放结果。

## 契约（先改）

- `docs/contracts/console.md` 补 `GET /api/semantics` 与 `POST /api/semantics/route` 两节。
- 路由回放只做确定性映射，不执行工具；能力绑定由调用方随请求传入（`bindings`）。

## 完成判据

- [x] 首页含语义层面板 -> `test_index_has_semantics_panel`
- [x] 语义层端点列出术语表 -> `test_semantics_endpoint_lists_schemes`
- [x] 路由回放端点返回命中 -> `test_semantics_route_endpoint_replays`
- [x] 全量门禁通过

## 反例

- 基线 `550872c`：首页没有 `id="semantics"`，没有 `/api/semantics` 与 `/api/semantics/route`
  路由，`build_console_app` 没有 `terminology` 参数，三个用例分别失败（404 / TypeError）。

## 5 问威胁建模

1. **数据**：术语表（概念、标签、映射）、路由回放输入文本与命中的能力绑定。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 租户 → 可见的术语表与路由命中。
4. **恶意输入最坏结果**：构造文本触发大量标签命中，返回大量绑定。缓解：路由只做确定性标签
   匹配，返回命中的能力与标签，不执行工具；工具真正执行前的授权仍由既有工具网关/审批把关。
5. **失败是否泄露信息**：存储不可用返回 `terminology_unavailable`，不泄露术语表全文外的内容。

## 范围外

- 术语表的写入/编辑 UI（写入仍走 CLI 或后续导入切片）。
- 能力绑定的持久化 store（本切片由调用方随请求传入，绑定 store 另开切片）。
- 通用导入（SLICE-227）、全局 Ask AI（SLICE-228）。

## 证据

- `docs/evidence/SLICE-226-semantics-panel.txt`
