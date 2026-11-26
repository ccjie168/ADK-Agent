# SLICE-303 售后演示的 mock 生态服务

状态: active
依据: 用户 2026-11-26 确认「售后值班 Agent + WorkBuddy/企业微信/夸克」方向与「先 mock 全链路」

## 意图

为售后值班场景提供可本地运行的 mock 生态：ITSM 工单、夸克网盘附件、企业微信
webhook。所有端点固定令牌、限大小、不落盘敏感内容，供后续 Agent 全链路验收脚本调用。
本切片只交付 mock 服务与场景说明；Agent、网关审批与验收脚本在后续切片。

## 契约（先改）

新增 `docs/demo/support-agent.md`：

- `GET /healthz` 免鉴权。
- 其余端点需要 `Authorization: Bearer <token>`，默认 token 来自 `MOCK_TOKEN`（缺省
  `mock-token`），错误返回 401 `{"error":"unauthorized"}`。
- `POST /itsm/tickets` 请求 `{title, description, priority}`；`priority` 取
  `low|normal|high`；成功 201 `{id, title, status, created_at}`；字段缺失/超长 400
  `invalid_ticket`。
- `GET /itsm/tickets/{id}` 返回工单或 404 `ticket_not_found`。
- `POST /quark/files` 请求 `{name, content_base64}`；名字 1–128、内容解码后 ≤1 MiB；
  成功 201 `{file_id, name, size}`；超限 413 `file_too_large`，非法 400 `invalid_file`。
- `GET /quark/files/{id}` 返回元数据（不回内容）。
- `POST /wecom/webhook` 请求 `{text}`；成功 201 `{sent: true, id}`。
- `GET /wecom/messages` 返回已发送消息（最多 100 条）。
- 运行：`python scripts/mock_services.py --port 8055`；`--print-token` 打印当前 token。

## 完成判据

- [ ] 免鉴权健康检查与其余端点鉴权 -> `test_mock_health_is_open_and_writes_need_token`
- [ ] 工单创建与查询往返 -> `test_mock_ticket_roundtrip`
- [ ] 附件大小上限与元数据不回内容 -> `test_mock_quark_limit_and_metadata`
- [ ] 微信 webhook 记录并可列出 -> `test_mock_wecom_records_messages`
- [ ] 场景文档与脚本参数一致 -> `test_support_demo_doc_matches_script`
- [ ] `--full` 门禁通过

## 反例

master 上没有这些端点与文档；上述用例失败（导入错误/404）。

## 5 问威胁建模

1. **数据**：mock 工单与附件只存在进程内存；测试与演示数据无真实凭据。
2. **调用方**：固定 Bearer token，来自环境变量，缺省值只用于本地演示。
3. **信任边界**：仅回环演示；不监听公网，不接入真实企业微信/夸克。
4. **恶意输入**：字段长度、base64 解码失败、附件上限都返回固定错误码。
5. **失败是否泄露信息**：错误只给错误码；附件查询不回内容；日志不打印 token 或内容。

## 范围外

- 真实 WorkBuddy OpenAPI、企业微信应用回调、夸克官方 Skill（后续切片）。
- Agent 与工具网关审批链路（下一片）。
- 持久化与多租户。

## 证据

- `docs/evidence/SLICE-303-support-mock.txt`
