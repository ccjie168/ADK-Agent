# SLICE-124 触发定义与存储

状态: gated
依据: ADR-0022 决定 6。自动化是独立服务，首期只做定时与 webhook 触发，只调用已发布、pinned 且声明了工具授权的 agent，不允许内联脚本。本切片先落触发定义、文件与 Postgres 存储、管理命令；执行服务是 SLICE-125。

## 意图（要什么，不写怎么写）

把一条自动化定义成不可变的触发记录，引用一个 pinned agent 版本，后续由独立服务执行。

- 触发有两种：`schedule` 与 `webhook`。
- `schedule` 用 `every_seconds`，最小 60 秒。不引入 cron 依赖，也不接受 cron 字符串。
- `webhook` 需要一个调用令牌。注册时只保存令牌的 SHA-256 哈希，明文不落盘、不回显、不进日志。
- 触发只引用 `agent_id`、`version` 与 `digest`。digest 必须是 `sha256:<64 hex>`，执行时还要与注册表记录一致。
- `input` 是固定的运行输入文本，最长 8000 字符。不允许脚本、模板表达式或 shell 片段。
- 同一租户下 `(tenant, trigger_id)` 唯一。重复登记相同内容幂等，不同内容冲突。
- 停用是幂等的显式写操作。
- 管理只走 CLI。执行服务与控制台管理留给 SLICE-125。

## 数据形状

`src/adk_agent/core/triggers.py`：

- `TriggerKind = Literal["schedule", "webhook"]`
- `AgentTrigger`（frozen，extra=forbid）
  - `trigger_id`：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
  - `tenant`：安全名
  - `agent_id`、`version`：安全名
  - `digest`：`^sha256:[0-9a-f]{64}$`
  - `kind`
  - `every_seconds: int | None`，schedule 必填且 `>=60`
  - `webhook_token_hash: str | None`，webhook 必填且 64 hex
  - `input: str = ""`，最长 8000
  - `enabled: bool = True`
  - `created_by`、`created_at`（带时区）
  - 校验：schedule 不得带 token 哈希，webhook 不得带 `every_seconds`。
- `hash_webhook_token(token: str) -> str`：令牌至少 16 字符，返回 SHA-256 hex。
- 错误：`TriggerError`、`TriggerNotFound`、`TriggerConflict`、`TriggerStoreUnavailable`。

存储键 `(tenant, trigger_id)`。文件布局 `<root>/<tenant>/<trigger_id>.json`；Postgres 表 `adk_triggers`，主键 `(tenant, trigger_id)`。

## 新增文件

- `src/adk_agent/core/triggers.py`
- `src/adk_agent/registry/triggers.py`
- `src/adk_agent/registry/triggers_postgres.py`
- `tests/test_triggers.py`
- `tests/test_triggers_postgres.py`
- `tests/test_cli_triggers.py`
- `docs/contracts/triggers.md`
- `docs/evidence/SLICE-124-trigger-definitions.txt`

## 修改文件

- `src/adk_agent/core/ports.py`、`src/adk_agent/core/__init__.py`
- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/cli.py`（`triggers list|register|disable`）
- `docs/contracts/cli.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] schedule 缺 `every_seconds` 或小于 60 时拒绝 -> `tests/test_triggers.py::test_schedule_requires_interval`
- [x] webhook 缺令牌哈希时拒绝，schedule 带哈希也拒绝 -> `::test_webhook_requires_token_hash`
- [x] 非法 digest、过短令牌、过长输入被拒绝 -> `::test_invalid_fields_are_rejected`
- [x] 令牌哈希确定，且存储内容不含明文令牌 -> `::test_token_is_hashed_and_not_stored`
- [x] 文件 store 往返、租户隔离、冲突与停用 -> `::test_file_store_roundtrip_and_disable`
- [x] Postgres store 往返与隔离 -> `tests/test_triggers_postgres.py::test_postgres_roundtrip_and_isolation`（无 `TEST_POSTGRES_URL` 跳过）
- [x] CLI 从环境变量读令牌登记、列出、停用，输出不含明文 -> `tests/test_cli_triggers.py::test_cli_register_list_disable`
- [x] CLI 令牌环境变量缺失或过短退出 1 -> `::test_cli_token_errors`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：schedule 接受缺失或过短的间隔 -> 期望 `::test_schedule_requires_interval` 失败
- [x] 反例 2：webhook 接受空令牌或把明文写入记录 -> 期望 `::test_token_is_hashed_and_not_stored` 失败
- [x] 反例 3：文件 store 的 `list` 返回其他租户记录 -> 期望 `::test_file_store_roundtrip_and_disable` 失败
- [x] 反例 4：CLI 把令牌回显到 stdout -> 期望 `::test_cli_register_list_disable` 失败

红态记录: 实现前 2 个模块报 `cannot import name 'AgentTrigger'`，CLI 报 `invalid choice: 'triggers'`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、触发 id、pinned agent 引用、间隔或令牌哈希、固定输入与启用状态。
2. **调用方**：管理员通过 CLI 登记与停用；SLICE-125 的执行服务读取定义。
3. **信任边界**：CLI 环境变量中的 webhook 令牌到文件或 Postgres；触发记录到执行服务。
4. **恶意输入最坏结果**：令牌明文进入仓库或日志（缓解：只接受环境变量，先哈希再存，输出与错误不回显）；触发指向未发布或已退役版本（缓解：digest 固定，执行时与注册表核对，SLICE-125 再加生命周期检查）；内联脚本或模板注入（缓解：只有固定 `input` 文本，长度受限，不做模板展开）；重复登记覆盖定义（缓解：同键不同内容冲突）；停用被绕过（缓解：执行服务只读 `enabled` 记录）。
5. **失败是否泄露信息**：错误只含触发 id 与字段名，不含令牌；记录里只有哈希。

## 范围外

- 执行服务、webhook 端点、调度循环、重试与幂等（SLICE-125）。
- 控制台面板与 HTTP 管理接口。
- cron 表达式、时区、日历假期。
- 通知与失败告警。
- 触发级别的审批流。SLICE-125 会拒绝声明了需审批工具授权的 agent。
- 触发记录修改。定义不可变，改定义用新 id。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-124-trigger-definitions.txt`
- 契约: `docs/contracts/triggers.md`
