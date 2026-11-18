# SLICE-153 控制台写路径与基础能力接口的能力校验

状态: gated
依据: PROGRESS 缺口清单第 6 条：读接口已由 SLICE-133 对齐到面板能力，写路径与基础能力接口仍只做认证加租户判断；
`POST /api/registry/load|unload` 与 `POST /api/tool-grants` 连能力检查都没有。

## 意图

1. 注册表按需加载与卸载需要 `registry.load`，先于请求体解析、配置 404 与租户检查。
2. 工具授权申请需要 `grants.request`，先于请求体解析与租户检查；工具授权面板的 Request 按钮
   已带同名能力标记，本切片补回归用例固定它。
3. `GET /api/runs`、`GET /api/plans`、`GET /api/traces/{trace_id}` 需要 `runs.read`；
   `GET /api/sessions` 需要 `sessions.read`；`POST /api/chat` 与 `POST /api/chat/stream` 需要 `chat.run`。
4. 上述接口缺少能力时返回固定的 403 `{"error": "forbidden"}`，文案不变。
5. 现有能力表不改：本切片不改变任何角色的能力集合，也不改变工具授权决定接口的 admin 限制
   （`grants.decide` 与 `connectors.manage` 的界面服务端不一致另立切片）。

## 契约（先改）

- `docs/contracts/console.md` 的能力清单、`/api/chat`、`/api/chat/stream`、`/api/plans`、
  `/api/traces/{trace_id}`、`/api/registry/load`、`/api/registry/unload`、`/api/tool-grants`、
  `/api/runs`、`/api/sessions` 各段补能力与检查顺序。

## 完成判据

- [x] operator 调用 `POST /api/registry/load` 得到 403，且坏请求体时仍是 403 -> `test_load_requires_registry_load`
- [x] operator 调用 `POST /api/registry/unload` 得到 403 -> `test_unload_requires_registry_load`
- [x] operator 申请工具授权得到 403 -> `test_tool_grant_request_requires_grants_request`
- [x] publisher 申请工具授权仍被处理 -> `test_publisher_can_request_a_tool_grant`
- [x] 工具授权面板的 Request 按钮带 `grants.request` 能力标记（回归保护） -> `test_grant_request_button_is_capability_gated`
- [x] 全量门禁通过

## 反例

- [x] 基线 operator 带坏请求体调用加载接口得到 400，能力未检查
- [x] 基线 operator 能提交工具授权申请并得到 201
- [x] 基线卸载、运行、计划、trace、会话与聊天接口不检查能力

## 5 问威胁建模

1. **数据**：注册表版本、工具授权申请、运行与 trace 事件、会话、聊天消息。
2. **调用方**：持有有效 token 的控制台用户，角色由 OIDC 或静态 token 决定。
3. **信任边界**：HTTP 请求到控制台进程内的存储与运行时。
4. **恶意输入最坏结果**：低权限用户按需加载或卸载 agent、自签工具授权申请、
   读取不该看的运行与会话（缓解：按操作与基础能力检查，先于解析与存储访问）。
5. **失败是否泄露信息**：统一固定 403 `forbidden`，不回显能力名或资源是否存在。

## 范围外

- `grants.decide`、`connectors.manage` 的界面服务端不一致另立切片，需要先定方向。
- 连接器申请提交、审批历史与 `/api/tenants` 的能力归属。
- 能力表本身的角色再设计；本切片不增删任何角色的能力。

## 证据

- `docs/evidence/SLICE-153-console-write-capabilities.txt`
