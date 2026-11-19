# 连接器申请契约

租户成员提交连接器登记申请，管理员批准或拒绝。批准时才写连接器存储。申请与连接器定义都不含密钥值，凭据只以 `secret://` 引用。

## `ConnectorRequest`

```json
{
  "request_id": "9f1c2d3e4a5b",
  "tenant": "acme",
  "spec": {
    "connector_id": "crm",
    "tenant": "acme",
    "kind": "http",
    "base_url": "https://crm.example.com",
    "methods": ["GET"],
    "path_prefixes": ["/v1/crm/"],
    "data_classes": ["internal"],
    "delegation": "service"
  },
  "reason": "Need CRM read access",
  "status": "pending",
  "requested_by": "alice",
  "requested_at": "2026-11-16T08:00:00Z",
  "decided_by": null,
  "decided_at": null,
  "decision_reason": "",
  "registered_connector": null
}
```

- `spec.tenant` 必须等于 `tenant`。全局连接器只能由管理员直接登记，不能走申请。
- `delegation` 描述执行身份模式，取 `service`（缺省，服务身份）、`controlled-service`（受控服务身份，
  高风险写需 HITL/审批）或 `obo-later`（OBO 委托，后置）。
- 示例省略了可选的 `auth_ref`，它只接受 `secret://` 引用，形状见 `credentials.md`。
- `status` 取 `pending`、`approved`、`denied`。终态不可再变。
- pending 时决定字段为空；approved 必须有 `decided_by`、`decided_at` 与 `registered_connector`。
- `reason` 是 1 到 2000 字符。

## 存储

- 键是 `request_id`。
- 文件布局：`<root>/<request_id>.json`。重复提交同一 id 相同内容幂等，不同内容冲突。
- Postgres：`adk_connector_requests(request_id text PRIMARY KEY, tenant text NOT NULL, definition jsonb NOT NULL, updated_at timestamptz NOT NULL)`。
- 决定用条件更新，只有一个决定生效；重复决定返回冲突。

## 控制台

`GET /api/connector-requests?tenant=&status=`：列出申请，按 `requested_at` 倒序。`tenant` 缺失时用调用方租户；非 `admin` 跨租户 403 `tenant_forbidden`。`status` 非法 400 `invalid_status`。未配置 404 `connector_requests_not_configured`，存储失败 503 `connector_request_store_unavailable`。

`POST /api/connector-requests`：请求 `{spec, reason}`，任何已认证主体都可以提交。`tenant` 与 `requested_by` 由服务端取调用主体；`spec.tenant` 不等于调用方租户时 400 `invalid_connector_request`。`request_id` 由服务端生成。成功 201，写 `connector.request` 审计。

`POST /api/connector-requests/{request_id}/decide`：仅 `admin`，非 admin 403 `forbidden`。请求 `{approved, reason}`。

- 拒绝：状态改为 denied，冻结连接器存储不变，写 `connector.request.decide`，审计状态 `denied`。
- 批准：先重跑凭据绑定检查，未绑定 400 `credential_unbound`；再登记连接器，同 id 不同定义 409 `connector_conflict`；登记成功后把申请标为 approved 并写 `registered_connector`。审计写 `connector.register` 与 `connector.request.decide`，状态 `ok`。
- 不存在 404 `connector_request_not_found`；已决定 409 `connector_request_already_decided`。
- 登记成功但申请更新失败时申请保持 pending；重试批准是幂等的，会完成剩余步骤。

## CLI

`adk-agent connector-requests list --tenant TENANT [--status STATUS] [--dir DIR | --db URL]`

`adk-agent connector-requests request --tenant TENANT --id ID --kind KIND --base-url URL [--auth-ref REF] [--methods LIST] [--path-prefixes LIST] [--data-classes LIST] --reason TEXT [--dir DIR | --db URL]`

`adk-agent connector-requests decide REQUEST_ID (--approve | --deny) [--reason TEXT] [--connectors-dir DIR | --registry-url URL] [--credentials-dir DIR | --credential-db URL] [--dir DIR | --db URL]`

- 申请存储未显式给出时读 `CONNECTOR_REQUEST_DATABASE_URL`。显式文件与数据库同时给出，或显式参数与环境变量冲突，退出 2。
- 申请记录：CLI 的 `requested_by` 是 `cli`，`request_id` 随机生成。
- `decide` 批准时需要连接器存储；拒绝时不需要，但给了也不写。
- 成功输出记录 JSON；失败 stderr 输出原因并退出 1。
- CLI 直接写存储，不产生审计，与现有 `connectors`、`lifecycle` 命令一致。
