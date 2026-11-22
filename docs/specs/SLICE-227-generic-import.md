# SLICE-227 通用导入

状态: gated
依据: ADR-0039 MVP 第 6 项（通用导入：术语表 / agent 定义 / RAG 语料）

## 意图

1. 新增通用导入入口 `section#import`（导航「数据」组），统一「上传 → 校验 → 落库 → 审计」管线。
2. `POST /api/import/terminology`：导入术语表 JSON（`ConceptScheme`），校验后落到 `terminology`
   store，失败不部分写入。
3. `POST /api/import/agent`：导入 agent manifest JSON，复用现有 registry publish 路径
   （manifest-only，不含工件字节），校验后落库，失败不部分写入。
4. 审计写入 `terminology.import` / `agent.import`。

## 契约（先改）

- `docs/contracts/console.md` 补 `POST /api/import/terminology` 与 `POST /api/import/agent` 两节。

## 完成判据

- [x] 首页含导入面板 -> `test_index_has_import_panel`
- [x] 术语表导入后可见 -> `test_import_terminology_endpoint`
- [x] agent 导入后可见 -> `test_import_agent_endpoint`
- [x] 全量门禁通过

## 反例

- 基线 `ce0c554`：首页没有 `id="import"`，没有 `/api/import/terminology` 与 `/api/import/agent`
  路由，三个用例分别失败（404）。

## 5 问威胁建模

1. **数据**：导入的术语表与 manifest，写审计事件。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 能力 → 允许导入的数据类型。
4. **恶意输入最坏结果**：越权导入、非法结构。缓解：校验 model（`ConceptScheme` / `AgentManifest`）
   fail-closed，导入先于写库校验，失败不落库；术语表只写调用方租户；agent 导入走既有 publish
   校验与签名路径。
5. **失败是否泄露信息**：返回结构化错误码（`invalid_scheme` / `invalid_manifest`），不泄露细节。

## 范围外

- RAG 语料的 UI 导入（需要 embedding 管线，复用现有 CLI `rag ingest`，后续切片）。
- 术语表 / agent 的批量 CSV 导入（MVP 只做 JSON）。
- 能力绑定的导入 store（另开切片）。

## 证据

- `docs/evidence/SLICE-227-generic-import.txt`
