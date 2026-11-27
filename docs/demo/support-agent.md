# 售后值班 Agent 场景（mock 版）

目标：用一条真实链路验证平台——A2A 入口、模型与密钥、检索、工具网关与审批、审计链、
配额、控制台。真实前端暂用 WorkBuddy/企业微信，本文件先定义本地 mock 的边界。

## 角色

- **WorkBuddy**：前端与 IM 入口。用户在 WorkBuddy App 或企业微信里提问，WorkBuddy 通过
  A2A 调 ADK 的售后专家。
- **ADK 售后专家**：检索产品 FAQ，查/建 ITSM 工单，把附件传到夸克网盘，必要时请人审批。
- **人工审批**：创建工单属于写操作，控制台批准后才执行。

## 本地 mock 服务

`scripts/mock_services.py` 启动一个 FastAPI 进程，模拟三个外部系统：

| 端点 | 用途 |
|---|---|
| `GET /healthz` | 免鉴权健康检查 |
| `POST /itsm/tickets`、`GET /itsm/tickets/{id}` | 工单创建与查询 |
| `POST /quark/files`、`GET /quark/files/{id}` | 附件上传与元数据（不回内容） |
| `POST /wecom/webhook`、`GET /wecom/messages` | 出站微信消息 |

鉴权：除 `/healthz` 外都要 `Authorization: Bearer $MOCK_TOKEN`，默认 `mock-token`。
未授权返回 401 `{"error":"unauthorized"}`。

### 工单

```json
POST /itsm/tickets
{"title": "无法登录", "description": "客户反馈验证码收不到", "priority": "high"}
```

成功 201：

```json
{"id": "t-1", "title": "无法登录", "status": "open", "created_at": "2026-11-26T..."}
```

`priority` 取 `low|normal|high`；字段缺失或超长返回 400 `invalid_ticket`；查询未知 id
返回 404 `ticket_not_found`。

### 附件

```json
POST /quark/files
{"name": "screenshot.png", "content_base64": "<base64>"}
```

成功 201 `{"file_id": "f-1", "name": "screenshot.png", "size": 1234}`；名字 1–128、
解码后 ≤1 MiB；超限 413 `file_too_large`，非法 400 `invalid_file`。`GET /quark/files/{id}`
只回元数据。

### 微信

```json
POST /wecom/webhook
{"text": "工单 t-1 已创建"}
```

成功 201 `{"sent": true, "id": "w-1"}`；`GET /wecom/messages` 返回最近 100 条。

## 运行

```bash
export MOCK_TOKEN=demo-token
./.venv/Scripts/python.exe scripts/mock_services.py --port 8055
```

`--print-token` 可只打印当前 token 后退出，便于脚本取值。

## 计划审批链路（mock）

`scripts/prove_support_demo.py` 自起 mock 服务并跑一个顺序计划：

| 步骤 | Agent | 说明 |
|---|---|---|
| `answer` | `support` | 无审批，返回处理建议 |
| `ticket` | `ticket_writer` | `risk_level=L3`，需人工审批，创建工单并通知微信 |

```bash
./.venv/Scripts/python.exe scripts/prove_support_demo.py
# 或拒绝审批、验证计划不会建单：
./.venv/Scripts/python.exe scripts/prove_support_demo.py --deny
```

成功时依次打印 `PASS` 并 `ALL PASS`，退出 0；拒绝审批时打印 `DENIED`，退出 2，
工单与微信消息都不会产生。审计写到 `audit.jsonl`（`--workdir` 可保留），链可校验，
包含 `orchestration.approval`、`orchestration.step` 与 `orchestration.run`。

## 在控制台里操作

交互审批（请求出现在控制台「审批」页，等你点批准）：

```bash
./.venv/Scripts/python.exe scripts/prove_support_demo.py   --interactive --wait-seconds 300   --approvals-dir C:/Users/Jie/.adk/state/approvals   --audit-file C:/Users/Jie/.adk/state/audit.jsonl
```

脚本打印 `WAITING approval <id>` 后停住；在控制台批准即继续，拒绝则退出 2，
`--wait-seconds` 内没人处理则打印 `TIMEOUT` 并退出 3。控制台若用
`--audit-file C:/Users/Jie/.adk/state/audit.jsonl` 启动，「审计」页能看到
`orchestration.*` 事件。

把 mock 服务登记成连接器，让「生态」「连接器」页可见：

```bash
./.venv/Scripts/python.exe scripts/support_demo_register.py   --connectors-dir C:/Users/Jie/.adk/state/connectors   --credentials-dir C:/Users/Jie/.adk/state/credentials
```

会写入 `mock-itsm`（`/itsm/`，L3）与 `mock-quark`（`/quark/`，L2），
凭据绑定 `mock-token-ref` 指向 `secret://local/mock_token`；启动控制台前把
`ADK_SECRET_LOCAL_MOCK_TOKEN` 设为 mock 的 token。登记只让连接器可见，
真正执行工具仍由工具网关与授权决定。

## A2A 入口（mock WorkBuddy）

`scripts/support_a2a_agent.py` 把同一个计划包成 ADK `BaseAgent`，模块级变量 `agent`
名称为 `support_flow`，可直接交给 `serve-a2a`。它读环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SUPPORT_MOCK_URL` | `http://127.0.0.1:8055` | mock 服务基址，只接受回环地址 |
| `SUPPORT_APPROVALS_DIR` | `support-approvals` | 审批请求目录，可与控制台共用 |
| `SUPPORT_AUDIT_FILE` | `support-audit.jsonl` | 计划审计链文件 |
| `SUPPORT_WAIT_SECONDS` | `120` | 等待审批的秒数，超时请求带 `expires_at` |

先按上文「运行」在另一个终端起 mock 服务，再单条命令起 A2A：

```bash
export SUPPORT_MOCK_URL=http://127.0.0.1:8055 SUPPORT_A2A_TOKEN=demo-token
./.venv/Scripts/python.exe -m adk_agent serve-a2a \
  --agent scripts/support_a2a_agent.py \
  --auth-token-env SUPPORT_A2A_TOKEN \
  --host 127.0.0.1 --port 8060
```

或让假 WorkBuddy 客户端把整条链路跑一遍（自起 mock 与 `serve-a2a`）：

```bash
./.venv/Scripts/python.exe scripts/prove_workbuddy_a2a.py
# 交互：停住等你从控制台批准，超时退出 3
./.venv/Scripts/python.exe scripts/prove_workbuddy_a2a.py --interactive --wait-seconds 300
# 拒绝审批：不建单、不发微信，退出 2
./.venv/Scripts/python.exe scripts/prove_workbuddy_a2a.py --deny
```

参数还有 `--workdir DIR`（保留状态）与 `--port N`（固定 A2A 端口）。
成功时打印 `PASS anonymous call rejected`、`PASS agent card returned`、
`PASS reply contains ticket`、`PASS ticket is open`、`PASS wecom notified`、
`PASS audit verified` 与 `ALL PASS`，退出 0。

调用是同步语义：`message/send` 会一直等到审批完成或超时。超时后计划抛
`ApprovalExpired`，A2A 返回 JSON-RPC 错误；真实 WorkBuddy 客户端需要设置足够长的超时。

## 后续切片

1. 售后专家 Agent 换成真实模型，工具经工具网关调用 mock 服务（当前计划里的
   `ticket_writer` 直接走 HTTP，不经过工具网关）。
2. 真实接入：WorkBuddy Enterprise OpenAPI（`pt_`/`ck_` 密钥）作为前端，夸克用官方
   `quarkclouddrive` Skill，企业微信用自建应用回调或群机器人。

注意：个人微信自动化（hook、网页协议）违反腾讯条款，不纳入任何阶段。
