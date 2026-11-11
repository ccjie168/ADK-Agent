# SLICE-008 核心契约与领域类型（M0-1）

状态: gated
依据: ADR-0002 第 2 条、第 3 条

## 意图（要什么，不写怎么写）

在 `src/adk_agent/core/` 用 Pydantic v2 定义五个领域契约：`AgentManifest`、`AgentRef`、`Principal`、`Invocation`、`AuditEvent`。它们是控制面、数据面、治理面共用的唯一形状。

契约的机器可读形式是 `docs/contracts/*.schema.json`，由 `scripts/export_contracts.py` 从模型生成并提交。模型与 schema 不一致时，测试失败。

本切片只定义类型、校验和 digest。不含适配器、网络、存储、编排行为。`core/` 不导入任何外部模块。

## 新增文件

- `src/adk_agent/core/__init__.py`
- `src/adk_agent/core/manifest.py`
- `src/adk_agent/core/identity.py`
- `src/adk_agent/core/invocation.py`
- `src/adk_agent/core/policy.py`
- `src/adk_agent/core/audit.py`
- `scripts/export_contracts.py`
- `tests/core/test_contracts.py`
- `docs/contracts/manifest.schema.json`（生成）
- `docs/contracts/agent_ref.schema.json`（生成）
- `docs/contracts/principal.schema.json`（生成）
- `docs/contracts/invocation.schema.json`（生成）
- `docs/contracts/audit_event.schema.json`（生成）

## 完成判据（可执行）

- [x] 五个模型可 JSON 往返，值不变 -> `tests/core/test_contracts.py::test_roundtrip`
- [x] 未知字段被拒绝 -> `::test_rejects_unknown_field`
- [x] `AgentManifest` 缺 id、version 或 owner 被拒绝 -> `::test_manifest_required`
- [x] `AgentRef` 缺 digest 被拒绝 -> `::test_agent_ref_requires_digest`
- [x] `Principal` 缺 tenant 或 subject 被拒绝 -> `::test_principal_required`
- [x] `Invocation` 缺 run_id 或 trace_id 被拒绝 -> `::test_invocation_required`
- [x] `AuditEvent` 缺 trace_id 或 principal 被拒绝 -> `::test_audit_required`
- [x] `AuditEvent.tenant` 与 `principal.tenant` 不一致时被拒绝 -> `::test_audit_tenant_matches_principal`
- [x] 带时区的 timestamp 通过，裸 datetime 被拒绝 -> `::test_audit_timestamp_tz_aware`
- [x] `manifest_digest` 对键顺序不敏感 -> `::test_digest_stable`
- [x] policy 字段变化时 digest 变化 -> `::test_digest_changes`
- [x] `docs/contracts/*.schema.json` 与模型一致 -> `::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`Principal(tenant="t")` 缺 subject -> `ValidationError` -> `::test_principal_required`
- [x] 反例 2：`AgentManifest` 带 `unknown="x"` -> `ValidationError` -> `::test_rejects_unknown_field`
- [x] 反例 3：`AgentRef(id="a", version="1")` 缺 digest -> `ValidationError` -> `::test_agent_ref_requires_digest`
- [x] 反例 4：`AuditEvent` 缺 `trace_id` -> `ValidationError` -> `::test_audit_required`
- [x] 反例 5：`AuditEvent(tenant="a")` 但 `principal.tenant="b"` -> `ValidationError` -> `::test_audit_tenant_matches_principal`
- [x] 反例 6：`AuditEvent` 的 timestamp 不带时区 -> `ValidationError` -> `::test_audit_timestamp_tz_aware`
- [x] 反例 7：手改 schema 文件不改模型 -> `::test_contracts_in_sync` 失败
- [x] 反例 8：同一 manifest 以不同键顺序序列化 -> digest 相同，先证明当前实现不存在 digest 函数 -> `::test_digest_stable`

## 契约

### AgentManifest

- `id: str`，非空
- `version: str`，非空，发布后不可变
- `owner: str`，非空
- `description: str = ""`
- `model_policy: ModelPolicy`
- `tool_grants: list[ToolGrant] = []`
- `data_scopes: list[DataClass] = []`
- `exposure: Exposure = "none"`
- `eval_suite: EvalSuite | None = None`
- `slo: Slo | None = None`

`ModelPolicy`：`provider_allowlist: list[str]`（至少一项）、`model_allowlist: list[str] = []`、`max_output_tokens: int | None`、`budget_usd: float | None`。

`EvalSuite`：`suite_id: str`、`version: str`、`pass_threshold: float`（0 到 1）。

`Slo`：`max_latency_ms: int | None`、`max_cost_usd: float | None`。

`Exposure`：`"none" | "mcp" | "http" | "a2a"`。

### AgentRef

- `id: str`，非空
- `version: str`，非空
- `digest: str`，非空

生产只认三元组，不认 latest。

### Principal

- `tenant: str`，非空
- `subject: str`，非空
- `kind: "human" | "service" | "agent"`
- `roles: list[str] = []`
- `attributes: dict[str, str] = {}`

### Invocation

- `run_id: str`，非空
- `trace_id: str`，非空
- `principal: Principal`
- `agent_ref: AgentRef`
- `input: str`
- `deadline: datetime | None`，带时区
- `budget_usd: float | None`，非负

### AuditEvent

- `event_id: str`，非空
- `run_id: str`，非空
- `trace_id: str`，非空
- `tenant: str`，必须等于 `principal.tenant`
- `principal: Principal`
- `agent_ref: AgentRef`
- `action: str`，非空
- `target: str`，非空
- `args_hash: str | None`
- `result_hash: str | None`
- `policy_decision_id: str | None`
- `data_classes: list[DataClass] = []`
- `latency_ms: int | None`
- `tokens: int | None`
- `cost_usd: float | None`
- `egress: "none" | "third_party"`
- `status: "ok" | "error" | "denied"`
- `error_code: str | None`
- `timestamp: datetime`，必须带时区，UTC

`DataClass`：`"public" | "internal" | "confidential" | "restricted"`。

### digest

`manifest_digest(manifest) -> str` 返回 SHA-256 十六进制。输入是 `manifest.model_dump(mode="json")` 的规范 JSON，使用 `sort_keys=True`、分隔符 `(",", ":")`、`ensure_ascii=False`。digest 不写入 manifest 自身。

### PublishedAgent

不单独生成 schema。它是注册表记录：`manifest`、`digest`、`signature`、`published_at`。`published_at` 必须带时区。

### schema 导出

`scripts/export_contracts.py` 暴露 `SCHEMAS` 映射和 `render()`。`render()` 返回 `{文件名: schema JSON 文本}`。脚本重写 `docs/contracts/`。`test_contracts_in_sync` 调用 `render()` 并与磁盘文件逐字比较。

## 5 问威胁建模（10 分钟）

1. **数据**：agent 身份、工具授权、数据分级、审计元数据。本切片不在 AuditEvent 存原始输入输出，只存 hash 和元数据。
2. **调用方**：控制面、运行时、编排器、审计管线。
3. **信任边界**：manifest 来自外部文件，Principal 来自 ingress，AuditEvent 来自运行时。三者都在边界解析。
4. **恶意输入最坏结果**：manifest 注入未知字段或超出范围的授权 -> `extra="forbid"` 和显式字段拒绝。Principal 伪造不在本切片范围，本切片只保证形状，身份验证留给 `IdentityProvider`。
5. **失败是否泄露信息**：校验错误只回显字段名和规则，不回显字段值。

## 证据

- 反例红: `pytest tests/core/test_contracts.py -q` -> `ModuleNotFoundError: No module named 'adk_agent.core'`，1 error
- 契约生成: `scripts/export_contracts.py` 连跑两次输出一致
- 实现后绿: `pytest tests/core/test_contracts.py -q` -> 12 passed
- `check.py --fast` -> format, lint, types, test, secrets 全 PASS，43 tests
- `check.py --full` -> format, lint, types, test, sast, deps, secrets 全 PASS
- 详见 `docs/evidence/SLICE-008-core-contracts.txt`
