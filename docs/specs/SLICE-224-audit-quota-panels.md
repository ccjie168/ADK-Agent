# SLICE-224 审计面板 + 配额面板

状态: gated
依据: ADR-0039 MVP 第 3 项（治理能力补全：审计面板 + 配额面板，只读查询可视化）

## 意图

1. 新增独立审计面板 `section#audit-panel`（导航加「审计」tab），复用已有 `GET /api/audit`，
   展示最近审计事件与时间，深链自总览页。
2. 给配额管理器加只读用量查询：`QuotaManager.usage(tenant, policy) -> QuotaUsage`
   （窗口运行数、活跃并发租约、策略上限），内存与 Postgres 两个后端都实现。
3. 新增 `GET /api/quota` 返回当前租户的 `QuotaUsage`，新增配额面板 `section#quota`
   （导航加「配额」tab），用 `.stat-card` 展示用量与上限。

## 契约（先改）

- `docs/contracts/console.md` 补 `GET /api/overview`（SLICE-223 遗漏）与 `GET /api/quota`。
- `QuotaManager` 是 `core/ports.py` 的端口，新增 `usage` 方法属于框架内部端口扩展，
  不新增独立契约文件；`QuotaUsage` 随 `core/quota.py` 导出。

## 完成判据

- [x] 首页含审计与配额面板 -> `test_index_has_audit_and_quota_panels`
- [x] 配额端点返回用量结构 -> `test_quota_endpoint_returns_usage`
- [x] 内存配额用量反映预留 -> `test_inmemory_quota_usage_reflects_runs`
- [x] 全量门禁通过

## 反例

- 基线 `8ad77bc`：首页没有 `id="audit-panel"` / `id="quota"`，没有 `/api/quota` 路由，
  `QuotaManager` 没有 `usage` 方法，三个用例分别失败（`AttributeError` 或 404）。

## 5 问威胁建模

1. **数据**：配额用量计数（运行数、活跃租约）、策略上限；审计事件。
2. **调用方**：控制台前端，经 OIDC / bearer 认证的 principal。
3. **信任边界**：principal 能力 → 可读的配额与审计数据。
4. **恶意输入最坏结果**：越权读其它租户配额或审计。缓解：`/api/quota` 只返回调用方租户，
   且沿用 `quota` 后端的 RLS；`/api/audit` 已有 `audit.read` 能力与租户过滤。
5. **失败是否泄露信息**：配额后端不可用返回 `quota_unavailable`，不泄露内部状态。

## 范围外

- 配额写入/调整（面板只读）。
- 审计事件的完整过滤 UI（时间/租户过滤面板属后续增强，本切片只展示最近事件）。
- RAG / 模型网关 / 语义层面板（SLICE-225/226）。

## 证据

- `docs/evidence/SLICE-224-audit-quota-panels.txt`
