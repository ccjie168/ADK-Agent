# SLICE-312 延迟审批接入演示服务（ADR-0049 切片 3）

状态: active
依据: ADR-0049 第 9 条已按用户 2026-11-28 的决定改为「立即回执」，A2A 任务状态推迟

## 意图

让售后演示的 MCP 与 A2A 调用不再阻塞：

1. `scripts/support_a2a_agent.py` 支持延迟模式（`SUPPORT_DEFER=1`）：计划需要审批时
   立即返回「已提交，等待审批，request_id=…」，并在本进程启动恢复器。
2. 恢复器看到决策后用同一 run_id 继续计划；写操作完成后结果体现在工单与审计里。
3. 通知可选：配置 `SUPPORT_NOTIFY_WEBHOOK_URL` 与 `SUPPORT_NOTIFY_SECRET_ENV` 时，
   提交与决定都通过 `WebhookNotifier` 推送；未配置则不发。

## 契约（先改）

`docs/demo/support-mcp.md` 增加「延迟审批」一节：

- `SUPPORT_DEFER`（默认 `0`）：`1` 时 `PlanExecutor(defer_approvals=True)`；
- `SUPPORT_NOTIFY_WEBHOOK_URL`、`SUPPORT_NOTIFY_SECRET_ENV`：可选通知渠道；
- 延迟模式下工具返回文本含 `request_id`；批准后由后台完成建单；
- 状态查询：控制台「审批」页看决策、`GET /api/plans` 看运行；不新增 HTTP 读接口。

## 完成判据

- [ ] 延迟模式下 MCP 调用 2 秒内返回回执且含 request id -> `test_mcp_deferred_call_returns_ack`
- [ ] 批准后后台恢复并建单（工单出现） -> `test_deferred_mcp_resumes_after_approval`
- [ ] 拒绝时不建单、不通知微信 -> `test_deferred_mcp_denial_leaves_no_ticket`
- [ ] 文档与脚本参数一致 -> `test_deferred_doc_matches_env`
- [ ] `--full` 门禁通过

## 反例

实现前 agent 只有同步路径，`SUPPORT_DEFER` 不存在，调用会一直等到审批；以上用例失败。

## 5 问威胁建模

1. **数据**：回执只含 request id 与步骤名，不含输入正文。
2. **调用方**：stdio 本机；恢复器在同一进程，无网络面。
3. **信任边界**：webhook 密钥从环境变量读取；未配置不发。
4. **恶意输入**：恢复器只处理本进程创建的 run_id 白名单。
5. **失败是否泄露信息**：回执与日志不含 token。

## 范围外

- A2A `input-required`（ADR-0049 决定 9 推迟）。
- 独立的 HTTP 状态接口与 MCP `support_status` 工具（0049-4）。

## 证据

- `docs/evidence/SLICE-312-deferred-demo-services.txt`
