# SLICE-122 连接器自助申请与审批

状态: gated
依据: ADR-0022 决定 5。连接器注册仍由管理员批准，租户用户只能提交申请。审批通过时才登记连接器，凭据仍只以 `secret://` 引用绑定。

## 意图（要什么，不写怎么写）

租户成员可以申请登记一个连接器，管理员批准或拒绝。批准时服务端执行与直接登记相同的校验，再写入连接器存储。

- 申请记录只含提议的 `ConnectorSpec`、理由、申请人、状态与决定信息。
- 申请只针对申请人自己的租户。`spec.tenant` 必须等于申请租户；全局连接器只能由管理员直接登记。
- 管理员批准时重跑凭据绑定检查，再调用连接器存储登记。登记成功后才把申请标记为 approved。
- 拒绝只改申请状态，不碰连接器存储。
- 申请与决定都写审计。批准同时写 `connector.register` 与 `connector.request.decide`。
- 状态机是 pending 到 approved 或 denied，终态不可再变。
- 部分失败可以重试。连接器登记幂等，重试批准会完成剩余步骤。已登记后拒绝不允许，管理员应改为停用连接器。

## 数据形状

`src/adk_agent/core/connector_requests.py`：

- `ConnectorRequest`（frozen，extra=forbid）
  - `request_id`：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，服务端生成
  - `tenant`：安全名
  - `spec`：`ConnectorSpec`，其 `tenant` 必须等于记录租户
  - `reason`：1 到 2000 字符
  - `status`：`pending`、`approved`、`denied`
  - `requested_by`、`requested_at`（带时区）
  - `decided_by`、`decided_at`、`decision_reason`
  - `registered_connector`：批准后登记的连接器 id
  - 校验：pending 时决定字段为空；终态时 `decided_by` 与 `decided_at` 必须存在；approved 必须有 `registered_connector`。
- 错误类型：`ConnectorRequestError`、`ConnectorRequestNotFound`、`ConnectorRequestConflict`、`ConnectorRequestStoreUnavailable`。

存储键是 `request_id`。文件布局 `<root>/<request_id>.json`；Postgres 表 `adk_connector_requests`，主键 `request_id`，定义存 jsonb，决定用条件更新保证只有一个赢家。

## 新增文件

- `src/adk_agent/core/connector_requests.py`
- `src/adk_agent/registry/connector_requests.py`
- `src/adk_agent/registry/connector_requests_postgres.py`
- `tests/test_connector_requests.py`
- `tests/test_connector_requests_postgres.py`
- `tests/test_console_connector_requests.py`
- `tests/test_cli_connector_requests.py`
- `docs/contracts/connector_requests.md`
- `docs/evidence/SLICE-122-connector-requests.txt`

## 修改文件

- `src/adk_agent/core/ports.py`、`src/adk_agent/core/__init__.py`
- `src/adk_agent/registry/credentials.py`（共享 `credential_is_bound` 检查）
- `src/adk_agent/console.py`（存储参数、三个路由、Connectors 面板的申请区）
- `src/adk_agent/cli.py`（`connector-requests list|request|decide`、控制台参数）
- `docs/contracts/console.md`、`docs/contracts/cli.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 申请的租户与 spec 租户不一致时模型拒绝 -> `tests/test_connector_requests.py::test_request_rejects_foreign_tenant_spec`
- [x] 文件 store 往返、列表过滤与决定状态机 -> `::test_file_store_roundtrip_and_decisions`
- [x] 决定并发只生效一次 -> `tests/test_connector_requests_postgres.py::test_postgres_decide_is_single_winner`（无 `TEST_POSTGRES_URL` 跳过）
- [x] 控制台申请、列出、批准并登记连接器 -> `tests/test_console_connector_requests.py::test_request_and_approve_registers_connector`
- [x] 批准时凭据未绑定返回 400，申请保持 pending -> `::test_approve_requires_enabled_binding`
- [x] 拒绝不改连接器存储 -> `::test_deny_does_not_register`
- [x] 非管理员不能决定 -> `::test_decide_requires_admin`
- [x] CLI 申请、列出、批准 -> `tests/test_cli_connector_requests.py`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：申请允许把 spec 租户写成别的租户 -> 期望 `::test_request_rejects_foreign_tenant_spec` 失败
- [x] 反例 2：已决定的申请还能再决定 -> 期望 `::test_file_store_roundtrip_and_decisions` 失败
- [x] 反例 3：批准未绑定凭据的连接器 -> 期望 `::test_approve_requires_enabled_binding` 失败
- [x] 反例 4：拒绝也写连接器存储 -> 期望 `::test_deny_does_not_register` 失败

红态记录: 实现前四个测试文件在收集阶段报 3 个 ImportError，缺少 `ConnectorRequest`。

## 5 问威胁建模（10 分钟）

1. **数据**：连接器定义（id、base_url、auth 引用、方法、路径前缀、数据分级）、理由、申请人、审批人。
2. **调用方**：租户成员提交申请；管理员审批；服务端在批准时写连接器存储。
3. **信任边界**：租户输入到共享请求存储；批准动作到连接器存储与出站策略。
4. **恶意输入最坏结果**：借申请绕过管理员直接开放出站（缓解：批准才登记，登记只由管理员触发）；把 spec 租户写成他人以偷用他人凭据（缓解：模型强制 spec.tenant 等于申请租户，批准时再查启用绑定）；内联凭据（缓解：`ConnectorSpec` 只接受 `secret://` 引用，base_url 不得含用户信息）；并发重复审批导致重复登记（缓解：登记幂等，决定用条件更新）。
5. **失败是否泄露信息**：错误只回错误码；审计记申请 id、租户与连接器 id，不记凭据值。

## 范围外

- 申请的过期与自动清理。
- 通知、邮件或站内消息。
- 控制面 `/v1/connector-requests` 与跨副本 HTTP 客户端。
- 租户自行停用或修改已登记连接器。
- 凭据值存储与密钥后端。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-122-connector-requests.txt`
- 契约: `docs/contracts/connector_requests.md`
