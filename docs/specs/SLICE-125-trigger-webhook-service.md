# SLICE-125 webhook 触发执行服务

状态: gated
依据: ADR-0022 决定 6。自动化是独立服务。本切片实现 webhook 触发路径，按租户计配额、写审计、拒绝声明了需审批工具的 agent，并对重复请求幂等。调度循环、多副本 slot 与重试留给 SLICE-126。

## 意图（要什么，不写怎么写）

新增 `serve-triggers`。调用方用触发登记时设置的令牌调用 `POST /v1/tenants/{tenant}/triggers/{trigger_id}/fire`，服务加载 pinned 版本并运行一次。

- 只接受 `webhook` 类型的触发。`schedule` 记录在这个入口返回 409。
- 令牌只比对哈希，使用常量时间比较。失败返回 401，不写审计。
- 触发必须启用，否则 409。
- 版本必须与触发记录里的 digest 一致；退役版本拒绝。
- agent 的 manifest 若声明了 `requires_approval` 的工具授权，拒绝运行并返回 409 `approval_required`。副作用审批不在本切片内，宁可不跑。
- 工件按信任库验签后加载。加载失败 502。
- 运行输入取请求体 `{"input": ...}`；缺省用触发记录的固定输入；最长 8000。
- 每次运行按租户配额，使用现有 `QuotaConfig` 与配额后端；超限 429。
- 每次运行写 `agent.run` 审计（`AgentRuntime` 负责）与一条 `trigger.fire` 审计，`source="trigger"`。
- 可选 `Idempotency-Key` 请求头，`^[A-Za-z0-9._-]{1,128}$`。同一键并发时只有一个运行，另一个返回 409 `fire_in_progress`；已完成后重复请求返回 200 与 `duplicate: true` 和原结果。
- 运行身份是 `tenant` 下 `trigger:<trigger_id>` 的服务主体。
- 服务只读触发与注册表，不写触发定义。

## 数据形状

`src/adk_agent/core/trigger_runs.py`：

- `TriggerFireStatus = Literal["running", "ok", "error", "denied"]`
- `TriggerFire`（frozen，extra=forbid）
  - `tenant`、`trigger_id`、`idempotency_key`（安全名，最多 128）
  - `run_id`、`trace_id`
  - `status`
  - `created_at`（带时区）、`finished_at`（可空）
  - `error_code: str | None`
- 校验：终态必须有 `finished_at`；running 不得有 `finished_at`。
- 错误：`TriggerFireError`、`TriggerFireConflict`、`TriggerFireStoreUnavailable`。

`TriggerFireStore` 端口：

- `claim(fire) -> TriggerFire`：已存在则返回已有记录。
- `finish(tenant, trigger_id, key, *, status, error_code=None, finished_at=...) -> TriggerFire`
- `get(tenant, trigger_id, key) -> TriggerFire | None`

文件布局 `<root>/<tenant>/<trigger_id>/<sha256(key)>.json`；Postgres 表 `adk_trigger_fires (tenant, trigger_id, idempotency_key, record jsonb, updated_at, PRIMARY KEY (tenant, trigger_id, idempotency_key))`，`claim` 用 `ON CONFLICT DO NOTHING` 后回读。

## 新增文件

- `src/adk_agent/core/trigger_runs.py`
- `src/adk_agent/registry/trigger_runs.py`
- `src/adk_agent/registry/trigger_runs_postgres.py`
- `src/adk_agent/triggers_service.py`
- `tests/test_trigger_runs.py`
- `tests/test_trigger_runs_postgres.py`
- `tests/test_triggers_service.py`
- `tests/test_cli_triggers_service.py`
- `docs/contracts/trigger_service.md`
- `docs/evidence/SLICE-125-trigger-webhook-service.txt`

## 修改文件

- `src/adk_agent/core/ports.py`、`src/adk_agent/core/__init__.py`
- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/cli.py`（`serve-triggers` 与其参数）
- `docs/contracts/cli.md`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 服务接口

`build_triggers_app(...) -> FastAPI`，依赖注入：

- `triggers: TriggerStore`
- `registry: AgentRegistry`
- `artifact_store: ArtifactStore`
- `trust: TrustStore`
- `loader: ArtifactLoader`
- `lifecycle: AgentLifecycleStore | None`
- `tool_grants: ToolGrantStore | None`
- `audit: AuditSink | None`
- `quota: QuotaManager | None`、`quota_config: QuotaConfig | None`
- `session_service: Any | None`（缺省 `InMemorySessionService`）
- `runner_factory: Callable[[Any], Any] | None`（测试注入；缺省 `build_runner`）
- `rate_limit: RateLimit | None`
- `metrics: MetricsRegistry | None`

`POST /v1/tenants/{tenant}/triggers/{trigger_id}/fire` 的响应：

```json
{"run_id": "...", "trace_id": "...", "status": "ok", "duplicate": false, "text": "..."}
```

错误码：400 `invalid_request`、401 `unauthorized`、404 `trigger_not_found`、409 `trigger_disabled`、409 `trigger_kind_mismatch`、409 `digest_mismatch`、409 `version_retired`、409 `approval_required`、409 `fire_in_progress`、429 `quota_exceeded`、502 `agent_load_failed`、500 `run_failed`。

`GET /healthz` 开放，返回 200。

## 完成判据（可执行）

- [ ] 触发 fire store 的 claim 单赢家、终态校验与幂等回读 -> `tests/test_trigger_runs.py`
- [ ] Postgres fire store 往返 -> `tests/test_trigger_runs_postgres.py`（无 `TEST_POSTGRES_URL` 跳过）
- [ ] 正确令牌运行一次，输入、审计与响应正确 -> `tests/test_triggers_service.py::test_fire_runs_the_pinned_agent`
- [ ] 错误令牌 401 且不写审计 -> `::test_wrong_token_is_unauthorized`
- [ ] 停用与 schedule 触发被拒 -> `::test_disabled_and_schedule_triggers_are_rejected`
- [ ] digest 不一致与退役版本被拒 -> `::test_digest_and_lifecycle_are_enforced`
- [ ] 需审批工具拒绝运行 -> `::test_approval_required_is_refused`
- [ ] 幂等键重复只运行一次 -> `::test_idempotency_key_runs_once`
- [ ] 配额超限 429 -> `::test_quota_exceeded`
- [ ] `serve-triggers` 参数与构建 -> `tests/test_cli_triggers_service.py`
- [ ] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [ ] 反例 1：错误令牌也能触发 -> 期望 `::test_wrong_token_is_unauthorized` 失败
- [ ] 反例 2：同一幂等键运行两次 -> 期望 `::test_idempotency_key_runs_once` 失败
- [ ] 反例 3：需审批工具的 agent 仍被运行 -> 期望 `::test_approval_required_is_refused` 失败
- [ ] 反例 4：digest 不一致仍加载 -> 期望 `::test_digest_and_lifecycle_are_enforced` 失败

红态记录: 待补，实现前运行。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、触发 id、webhook 令牌、幂等键、固定或请求输入、pinned 版本与 digest。
2. **调用方**：持有触发令牌的外部系统；服务读取触发、注册表、工件与授权存储。
3. **信任边界**：公网 webhook 到服务；令牌到触发记录；注册表工件到进程内执行。
4. **恶意输入最坏结果**：令牌爆破（缓解：只比对哈希、常量时间、可选限流、失败不写审计但计数）；重放请求重复产生副作用（缓解：幂等键单赢家）；调用未发布或已退役版本（缓解：pinned digest 与生命周期检查）；借需审批工具绕过人工决定（缓解：发现 `requires_approval` 直接拒绝）；输入过大或含脚本（缓解：纯文本上限 8000，不解析模板）；服务无鉴权暴露（缓解：fire 必须令牌，`/healthz` 只读；部署文档要求内网或网关前）。
5. **失败是否泄露信息**：错误只回错误码；审计记输入哈希与结果哈希，不记原文；日志不回显令牌。

## 范围外

- 调度循环、多副本 slot、重试（SLICE-126）。
- 审计中的原文、通知与失败告警。
- 控制台管理界面。
- 触发级别的审批工作流。需审批工具直接拒绝。
- 触发器修改。定义不可变。
- 模型通道扩展。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-125-trigger-webhook-service.txt`
- 契约: `docs/contracts/trigger_service.md`
