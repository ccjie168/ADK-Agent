# SLICE-301 审计读取的稳定排序与游标分页

状态: active
依据: PROGRESS 记录的「同刻事件超过 1000 条读取窗口」；SLICE-286 只统一了控制台返回值的排序

## 意图

审计读取在截断窗口时使用的顺序与契约不一致：文件后端按插入顺序、Postgres 按
`sequence` 截断，返回前才在控制台按 `(timestamp, event_id)` 重排。同一时间戳超过
1000 条时，被截断的窗口可能不含契约意义上的“最近”事件，且更早的同刻事件无法读取。
本切片把截断顺序统一为 `(timestamp, event_id)`，并给审计服务与控制台内部读取加
`before_timestamp` + `before_event_id` 游标，使控制台可以跨页读取。

## 契约（先改）

`docs/contracts/console.md` 的 `/api/audit`：

- 删除「超出该窗口的极端同刻事件不在契约内」；改为：排序与窗口都按
  `(timestamp, event_id)`，控制台内部按游标分页，同刻事件超过 1000 条也能读全。

`docs/contracts/cli.md` 的 `GET /v1/events`：

- 新增 `before_timestamp` 与 `before_event_id`，必须同时给出；只在 `order=desc` 时有效；
  半对或格式错误返回 400 `invalid_cursor`。
- 游标是开区间：只返回 `(timestamp, event_id)` 严格小于游标的事件。

## 完成判据

- [ ] 文件后端同刻事件按 event_id 截断 -> `test_file_query_orders_same_timestamp_by_event_id`
- [ ] 游标分页无重复无遗漏 -> `test_file_query_cursor_pages_same_timestamp`
- [ ] 审计服务接受游标并拒绝半对 -> `test_audit_service_cursor_params`
- [ ] HTTP 查询客户端发送游标 -> `test_http_query_sends_cursor`
- [ ] 控制台在同刻 1200 条乱序写入时取到最近 200 条 -> `test_console_audit_reads_past_same_timestamp_window`
- [ ] `--full` 门禁通过

## 反例

master 上 `query_events` 按插入顺序截断，`GET /v1/events` 不认识游标参数，
控制台只读一页 1000 条；上述用例失败。

## 5 问威胁建模

1. **数据**：审计事件本身，无新增字段；游标只含时间戳与 event_id。
2. **调用方**：控制台内部读取；审计服务的游标沿用既有鉴权与租户过滤。
3. **信任边界**：游标值来自已读事件，仍经过租户过滤；不引入路径或 SQL 拼接。
4. **恶意输入**：时间格式非法、event_id 非法、半对游标都返回 400 固定错误码。
5. **失败是否泄露信息**：错误只给参数名/错误码，不返回查询或存储细节。

## 范围外

- 控制台 `/api/audit` 对外的游标参数（页面仍只要最近 N 条）。
- Postgres 事件的物理排序索引（沿用现有 occurred_at 索引，event_id 为次级键）。
- 沙箱 worker 的模型提供方 lookup（下一片）。

## 证据

- `docs/evidence/SLICE-301-audit-cursor.txt`
