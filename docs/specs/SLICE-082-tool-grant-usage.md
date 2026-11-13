# SLICE-082 工具授权使用统计与到期提示

状态: merged
依据: ADR-0011，SLICE-081，方向评审 Phase C。

## 意图（要什么，不写怎么写）

审批入口有了，但操作者看不到“临时授权有没有被用、用到什么程度、哪些快到期”。这一刀补运营视图。

- `AuditEvent` 增加可选 `policy_version`；`ToolGuard` 在 `tool.call` 事件里写入策略版本（`grants-v1` 或 `grants-v2`）。
- 控制台新增 `GET /api/tool-grants/usage?tenant=`，按工具聚合最近的 `tool.call` 事件：允许、拒绝、临时授权放行次数。
- Grants 面板加使用统计表；已批准且 24 小时内到期的请求显示 expiring 徽标。
- 不做后台提醒任务与外部通知；到期仍由读取时判断。

## 新增文件

- `tests/test_tool_grant_usage.py`
- `docs/evidence/SLICE-082-tool-grant-usage.txt`

## 修改文件

- `src/adk_agent/core/audit.py`、`scripts/export_contracts.py`、`docs/contracts/audit_event.schema.json`
- `src/adk_agent/tools/guard.py`
- `src/adk_agent/console.py`
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditEvent += policy_version: str | null

GET /api/tool-grants/usage?tenant= -> [
  {"tool_id": "crm.read", "allowed": 3, "denied": 1, "temporary": 2}
]

Grants 面板：
  approved 且 expires_at - now <= 24h -> expiring 徽标
```

## 完成判据（可执行）

- [x] 允许事件带策略版本 -> `tests/test_tool_grant_usage.py::test_allowed_event_version`
- [x] 拒绝事件带策略版本 -> `::test_denied_event_version`
- [x] 临时授权放行标记 grants-v2 -> `::test_temporary_grant_version`
- [x] 使用统计聚合 -> `::test_usage_aggregates`
- [x] 跨租户不可见 -> `::test_usage_tenant_scope`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`AuditEvent(policy_version=...)` -> 当前 `ValidationError`
- [x] 反例 2：`GET /api/tool-grants/usage` -> 当前 404
- [x] 反例 3：临时授权放行的事件没有版本标记 -> 当前无此字段

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 与生成的 `audit_event.schema.json`。

## 5 问威胁建模（10 分钟）

1. **数据**：工具名、允许/拒绝计数、策略版本、到期时间。
2. **调用方**：控制台用户。
3. **信任边界**：审计缓冲/服务到运营视图。
4. **恶意输入最坏结果**：跨租户看到别家统计（缓解：租户过滤）；把临时授权用量算进 manifest 授权（缓解：按 policy_version 区分）。
5. **失败是否泄露信息**：审计不可用返回固定 502。

## 范围外

- 后台到期提醒、邮件或 IM 通知。
- 按 run、按时间窗的细粒度统计。
- 授权的自动续期。

## 证据

- 反例红: `docs/evidence/SLICE-082-tool-grant-usage.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真控制台
