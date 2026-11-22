# SLICE-223 控制台总览首页

状态: gated
依据: ADR-0039 MVP 第 2 项（总览首页，聚合卡片网格，深链到各面板）

## 意图

1. 新增 `GET /api/overview`（控制台内部只读接口），返回一组聚合卡片：每张卡片有 `key` /
   `label` / `value` / `panel`，`panel` 是深链目标面板 id。MVP 聚合四张：待审批（approvals）、
   已注册 Agent（registry）、工具（tools）、待处理授权（grants）。
2. 新增总览面板 `section#overview`，用 SLICE-222 的 `.metric-grid` + `.stat-card` 渲染卡片，
   卡片点击深链到对应面板（`showTab(panel)`）。
3. 对未配置或无权限的卡片，`value` 返回 `null`，前端显示「未配置 / 无权」，不报错。

## 契约（先改）

无对外接口变更。`/api/overview` 是控制台内部只读接口，由前端消费，不进 `docs/contracts/`。

## 完成判据

- [x] 总览端点返回四张卡片结构 -> `test_overview_endpoint_returns_cards`
- [x] 无权限的卡片 value 为 null -> `test_overview_null_for_forbidden_card`
- [x] 首页含总览面板与卡片网格 -> `test_index_has_overview_panel`
- [x] 全量门禁通过

## 反例

- 基线 `7e87006`：没有 `/api/overview` 路由（404），首页没有 `id="overview"` 面板，
  三个用例分别失败。

## 5 问威胁建模

1. **数据**：各 store 的计数（待审批数、agent 数、工具数、待授权数），无内容明细。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 能力 → 可读的指标卡片。
4. **恶意输入最坏结果**：越权读取某张卡片计数。缓解：每张卡片只在调用方有对应能力时填
   `value`，否则 `null`；计数不含明细，泄露面最小。
5. **失败是否泄露信息**：store 不可用返回 `null` 而非异常细节，不泄露后端状态。

## 范围外

- 审计 / 配额 / RAG / 模型网关 / 语义层的卡片（面板在 SLICE-224/225/226，其卡片随面板补）。
- 卡片的实时刷新（MVP 用进入面板时拉一次）。
- 前端框架与构建链（ADR-0039 已否决）。

## 证据

- `docs/evidence/SLICE-223-console-overview-homepage.txt`
