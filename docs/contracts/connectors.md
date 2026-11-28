# 连接器契约

连接器是外部 HTTP API 的受治理声明：租户、`base_url`、方法/路径白名单、密钥引用、
风险等级与审批继承。定义在 `adk_agent.core.connectors.ConnectorSpec`。

## ConnectorSpec

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `connector_id` | string，`^[A-Za-z0-9][A-Za-z0-9._+-]*$` | 连接器 id，同时是连接器级工具名 |
| `tenant` | string 或 null | 不填即全局 |
| `kind` | `http` / `openapi` / `mcp` | 执行方式；`openapi` 与 `http` 目前同一执行路径 |
| `base_url` | string | 必须 https，或回环 host 上的 http；禁止内嵌凭据 |
| `auth_ref` | `secret://...` 或 null | Bearer 令牌的密钥引用 |
| `methods` | 非空列表 | 允许的 HTTP 方法 |
| `path_prefixes` | 非空列表 | 允许的路径前缀，不得含 `..` |
| `data_classes` | 列表 | 数据分级 |
| `timeout_seconds` / `max_response_bytes` | int | 请求限制 |
| `risk_level` | `L1`..`L4` 或 null | 工具级风险；L3/L4 需要审批 |
| `delegation` | `service` / `controlled-service` / `obo-later` | 委派模式 |
| `enabled` | bool | 停用的连接器不生成工具 |
| `operations` | 列表（additive，缺省 `[]`） | OpenAPI 导入产物，见下 |

### operations（SLICE-320 新增）

```json
{
  "tool_id": "itsm.ticket.create",
  "path": "/tickets/{id}",
  "method": "POST",
  "risk_level": "L3",
  "data_classes": ["confidential"],
  "write": true
}
```

- `tool_id` 符合工具名规则，且以 `<connector_id>.` 开头；同一次导入里不得重复。
- `path` 以 `/` 开头，可含 `{name}` 形式的路径参数；路径段不得为 `..`，不得含反斜杠。
- `method` 是 `HttpMethod`。
- `risk_level` / `data_classes` / `write` 是操作的治理属性；网关注册的工具有同样的
  `risk_level`、`data_classes`、`write`、`requires_approval`，L3/L4 需要 HITL 审批与
  幂等键（与工具目录展示的值一致）。连接器自身的 `risk_level`/`data_classes` 是下限：
  工具的有效风险取两者较高者，数据分级取并集（`ConnectorSpec.operation_governance`）。
- 同一个连接器里 `operations` 的 `tool_id` 必须唯一，模型校验即拒绝重复。
- 工具名在工具网关里全局唯一，由**存储层**保证：`FileConnectorStore.add` 与
  `PostgresConnectorStore.add` 都会拒绝新连接器的 id 或任一操作 `tool_id` 已被另一个
  连接器占用的情况（`ConnectorToolIdConflict`）。控制面 `POST /v1/connectors`、控制台
  `POST /api/connectors` 与连接器申请批准都走 `add`，因此都被覆盖。
  `connectors import-openapi` 在存储支持列出全部连接器时（文件目录）写入前再预检一次，
  冲突报 `tool_id_conflict` 且不写入；走 `--registry-url` 时由服务端拒绝，返回
  409 `tool_id_conflict`，导入命令同样不写入。
- 有 `operations` 的连接器在网关里为每个操作生成一个工具：工具名即 `tool_id`，
  调用参数为 `query`、`path_params`、`json_body`；方法固定、路径参数拒绝 `/`、`\`、
  `..` 后 URL 编码，再过连接器的 `path_prefixes` 校验。没有 `operations` 的连接器仍
  生成连接器级工具（`path`、`method`、`query`、`json_body`）。
- `connector_tool_entries()` 对含 `operations` 的连接器同样按操作展开，不再产出
  连接器级条目。

## OpenAPI 导入

```
adk-agent connector import-openapi --spec FILE --connector-id ID \
    [--tenant T] [--base-url URL] \
    (--connectors-dir DIR | --registry-url URL) \
    [--tool-catalog PATH] [--dry-run]
```

规则：

- `base_url` 取 `--base-url`，否则 `servers[0].url`；相对地址或缺省即 `missing_server`。
- 每个含 `operationId` 的操作生成一个工具：方法取操作键（`get`/`put`/`post`/`delete`/
  `patch`/`head`），路径取文档路径（`{name}` 原样保留）。
- `methods` 与 `path_prefixes` 取所有生成操作的集合；路径前缀截到第一个 `{` 之前
  （`/tickets{id}` → `/tickets`，`/tickets/{id}` → `/tickets/`）。
- `data_classes` 取操作、path item、文档顶层的 `x-data-classes`（必须是合法分级）；
  否则 `internal`。
- `risk_level` 取操作、path item、文档顶层的 `x-risk-level`，都没有则 L2；
  L3/L4 的工具 `requires_approval=true`。
- 没有 `operationId` 的操作跳过并在输出里列出（`skipped`）；同一个文档里两次出现
  同一个 `operationId` 即 `duplicate_operation_id`。
- 超过 200 个生成操作即 `too_many_operations`，不写入任何东西。
- `--dry-run` 只打印将写入的连接器与工具，不落盘。

错误码（固定字符串）：`spec_unreadable`、`spec_invalid`、`missing_server`、
`no_operations`、`too_many_operations`、`invalid_data_class`、`invalid_risk_level`、
`duplicate_operation_id`、`catalog_unreadable`、`catalog_conflict`、`tool_id_conflict`。

## 工具目录合并

`--tool-catalog PATH` 给出时，导入的工具条目合并进该文件的 `tools` 数组：

- 相同 `tool_id` 且内容相同：幂等，不重复写入。
- 相同 `tool_id` 但内容不同：`catalog_conflict`，整次导入失败，连接器也不写入。
- 目录文件不是合法 JSON：`catalog_unreadable`，同样不写入连接器。
- 新文件：创建 `{"version": 1, "tools": [...]}`。

## 回滚注意

`operations` 是 additive 字段，但 `ConnectorSpec` 是 `extra="forbid"`：回退到不认识该
字段的版本后，导入过的连接器记录会让 `FileConnectorStore.list()` 整体失败（一条坏记录
连坐全部），`serve-tool-gateway` 与 `connectors list` 都会起不来。回退前先删除或用
旧版重新登记这些连接器；更长期的修法是让文件存储逐条容错（记录为后续项）。
