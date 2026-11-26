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

## 后续切片

1. 售后专家 Agent：`ScriptedLlm`（演示）或真实模型，工具经工具网关调用 mock 服务；
   建工单走 L3 审批。
2. 验收脚本：起 mock、工具网关、审计、`serve-a2a`，用 mock WorkBuddy 客户端发问，
   批准工单，校验审计链与微信消息。
3. 真实接入：WorkBuddy Enterprise OpenAPI（`pt_`/`ck_` 密钥）作为前端，夸克用官方
   `quarkclouddrive` Skill，企业微信用自建应用回调或群机器人。

注意：个人微信自动化（hook、网页协议）违反腾讯条款，不纳入任何阶段。
