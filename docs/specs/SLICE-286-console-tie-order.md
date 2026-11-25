# SLICE-286 控制台审计事件的同刻顺序

状态: gated
依据: PROGRESS 第 16 条既有缺口（同一时间戳事件在 `limit` 边界上的子集与后端方向有关）

## 意图

控制台的 `/api/audit`、`/api/runs` 与 trace 都走 `_query_events`。它只按 `timestamp` 排序，
同一时间戳的事件保留后端的返回顺序：内存 `ListAuditSink` 是插入顺序，`FileAuditQuery` 是
最新的在前，HTTP/Postgres 又各不相同。于是 `limit` 截断时「同一时刻取哪几条」随后端变化，
同一个请求在两个部署上可能返回不同子集。

修复：`_query_events` 的排序键改为 `(timestamp, event_id)`，同刻按 `event_id` 升序，
与后端插入顺序无关。审计服务 `GET /v1/events` 的契约明写「同一时间按写入顺序」，本切片不改它。

## 契约（先改）

- `docs/contracts/console.md` 的 `GET /api/audit` 一节：写明同刻按 `event_id` 升序，不依赖后端顺序。

## 完成判据

- [ ] 同刻事件按 `event_id` 升序 -> `test_console_audit_orders_equal_timestamps_by_event_id`
- [ ] 内存与文件后端对同刻事件给出相同顺序 -> `test_console_audit_ties_agree_between_backends`
- [ ] 不同时间戳的顺序不变 -> `test_console_audit_keeps_distinct_timestamps_in_order`

## 反例

实现前，同刻事件按插入顺序返回（内存后端）或按后端倒序（文件后端），前两条用例失败；
不同时间戳的用例在旧代码上通过，作为回归保护。

## 5 问威胁建模

1. **数据**：审计事件的排序键（时间戳、事件 id）；不新增返回字段。
2. **调用方**：所有 `audit.read` 主体；排序不改变租户过滤与能力检查。
3. **信任边界**：`event_id` 由平台生成；读取端只排序，不做链校验。
4. **恶意输入**：无新输入；`limit` 边界由既有校验约束。
5. **失败是否泄露信息**：无变化。

## 范围外

- 审计服务 `GET /v1/events` 的「写入顺序」语义。
- Postgres 侧按 sequence 排序的优化。

## 证据

- `docs/evidence/SLICE-286-console-tie-order.txt`
