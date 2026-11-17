# SLICE-128 执行层级与发布门槛

状态: gated
依据: ADR-0024 第 1、5 条。沙箱 worker 尚未实现，先把层级写进契约与发布、加载边界，让 `sandboxed` 工件在没有后端时既发不出去也跑不起来。

## 意图（要什么，不写怎么写）

1. `AgentManifest` 增加执行层级字段，取 `in_process` 或 `sandboxed`。
2. 新发布的 manifest 必须显式声明层级；缺失或非法一律拒绝。
3. 没有 agent 沙箱后端时，`sandboxed` 在发布与加载两处都被拒绝，错误码 `sandbox_unavailable`。
4. 历史记录没有该字段时按 `in_process` 读取，digest 不变，不做数据迁移。
5. 组合器产物声明 `in_process`；脚手架产物在本切片也声明 `in_process`，等 SLICE-129 有后端后再翻成 `sandboxed`。这是进入时的排序决定，写进证据，不静默放宽。

## 数据形状

`src/adk_agent/core/manifest.py`：

- `ExecutionTier = Literal["in_process", "sandboxed"]`
- `AgentManifest.execution_tier: ExecutionTier | None = None`
  - `None` 只用于读取历史记录，语义等同 `in_process`。
  - 非法值由 pydantic 拒绝。
- `declared_execution_tier(data: Mapping[str, Any]) -> ExecutionTier`
  - 发布边界用。缺失或 `None` 抛 `ValueError("manifest must declare execution_tier")`。
- `manifest_digest(manifest)`：`execution_tier` 为 `None` 时从 canonical payload 里去掉该键，历史记录 digest 保持原值；声明了层级的新 manifest，层级进入 digest。

`src/adk_agent/sandbox/agent.py`（新文件，agent 级沙箱的入口，本切片只有能力探测）：

- `AgentSandboxUnavailable(RuntimeError)`
- `agent_sandbox_backend() -> object | None`：注册的后端，当前恒为 `None`。
- `set_agent_sandbox_backend(backend: object | None) -> None`：SLICE-129 与测试用。
- `agent_sandbox_available() -> bool`
- `require_execution_supported(manifest: AgentManifest) -> None`
  - 层级是 `sandboxed` 且没有后端时抛 `AgentSandboxUnavailable("agent sandbox is not available")`。

## 契约（先改）

- `docs/contracts/manifest.schema.json`：重新导出，含 `execution_tier`。
- `docs/contracts/README.md`：说明层级含义、历史记录缺省语义与 digest 规则。
- `docs/contracts/cli.md`：`publish` 必须显式声明层级；`sandboxed` 无后端时退出 1；`new` 生成的 manifest 声明 `in_process`；`compose` 产物声明 `in_process`。
- `docs/contracts/registry_service.md`：`POST /v1/agents` 缺少层级返回 400 `invalid_record`；声明 `sandboxed` 且无后端返回 409 `sandbox_unavailable`。
- `docs/contracts/console.md`：按需加载遇到 `sandboxed` 记录返回 409 `sandbox_unavailable`。
- `docs/contracts/trigger_service.md`：触发执行遇到 `sandboxed` 记录返回 409 `sandbox_unavailable`。

## 新增文件

- `src/adk_agent/sandbox/agent.py`
- `tests/core/test_execution_tier.py`
- `tests/registry/test_execution_tier_boundary.py`
- `docs/evidence/SLICE-128-execution-tier.txt`

## 修改文件

- `src/adk_agent/core/manifest.py`、`src/adk_agent/core/__init__.py`
- `src/adk_agent/registry/loader.py`（`load_agent` 先过层级门槛）
- `src/adk_agent/registry/service.py`（发布边界）
- `src/adk_agent/cli.py`（`publish` 边界）
- `src/adk_agent/console.py`（按需加载映射 409）
- `src/adk_agent/triggers_service.py`（映射 409）
- `src/adk_agent/compose/__init__.py`（声明 `in_process`）
- `src/adk_agent/templates/builtin.py`（生成的 manifest 声明 `in_process`）
- `scripts/export_contracts.py` 产物 `docs/contracts/manifest.schema.json`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 历史 manifest 没有层级 -> 读为 `None`，digest 与去掉该键的 canonical payload 一致 -> `tests/core/test_execution_tier.py::test_legacy_manifest_digest_is_unchanged`
- [x] 声明层级后 digest 随层级变化 -> `::test_tier_is_part_of_the_digest`
- [x] 非法层级被拒 -> `::test_unknown_tier_is_rejected`
- [x] `declared_execution_tier` 缺键或 `None` 抛错，合法值原样返回 -> `::test_declared_tier_rules`
- [x] 服务发布缺层级 -> 400 `invalid_record` -> `tests/registry/test_execution_tier_boundary.py::test_publish_requires_a_declared_tier`
- [x] 服务发布 `sandboxed` 且无后端 -> 409 `sandbox_unavailable` -> `::test_sandboxed_publish_needs_a_backend`
- [x] 服务发布 `sandboxed` 且后端可用 -> 201 -> `::test_sandboxed_publish_with_backend`
- [x] `load_agent` 遇 `sandboxed` 记录抛 `AgentSandboxUnavailable`，后端可用时放行 -> `::test_load_agent_gates_sandboxed_records`
- [x] CLI `publish` 缺层级或 `sandboxed` 退出 1，`in_process` 成功 -> `tests/test_cli_publish_tier.py`
- [x] 控制台按需加载 `sandboxed` -> 409 `sandbox_unavailable` -> `tests/test_console_execution_tier.py`
- [x] 触发执行 `sandboxed` -> 409 `sandbox_unavailable`，runner 未调用 -> `tests/test_triggers_service.py::test_sandboxed_trigger_is_refused`
- [x] 组合器与脚手架产物声明 `in_process` -> 既有 compose 测试与 `tests/test_templates.py` 增补断言
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：服务接受没有 `execution_tier` 的 manifest -> 期望 `::test_publish_requires_a_declared_tier` 失败
- [x] 反例 2：无后端时服务接受 `sandboxed` -> 期望 `::test_sandboxed_publish_needs_a_backend` 失败
- [x] 反例 3：`load_agent` 在无后端时照常 `exec` `sandboxed` 工件 -> 期望 `::test_load_agent_gates_sandboxed_records` 失败
- [x] 反例 4：历史 manifest 因新增字段 digest 变化 -> 期望 `::test_legacy_manifest_digest_is_unchanged` 失败
- [x] 反例 5：触发服务在无后端时执行 `sandboxed` 触发 -> 期望 `::test_sandboxed_trigger_is_refused` 失败

红态记录: 见证据文件。

## 5 问威胁建模（10 分钟）

1. **数据**：manifest 的 `execution_tier`、digest、已发布记录、触发定义。
2. **调用方**：CLI `publish`、注册表 HTTP 服务、控制台按需加载、触发执行服务、组合器与脚手架。
3. **信任边界**：发布边界（新记录进入）、加载边界（记录变成进程内代码）。
4. **恶意输入最坏结果**：手工发布 `sandboxed` 记录绕过发布门槛（缓解：加载边界再查一次）；把 `in_process` 声明用于租户代码（本切片无法区分组合器产物与手写 manifest，且没有可执行的替代层级，所以发布行为等价于现状。收紧点定在 SLICE-129 后端可用时：publish 默认 `sandboxed`，`in_process` 只接受平台构建密钥签名的工件。该缺口写进证据与 PROGRESS，不静默忽略）；历史记录被误判为 `sandboxed`（缓解：缺省按 `in_process`，digest 不变）。
5. **失败是否泄露信息**：错误只含 `sandbox_unavailable` 与 manifest 名，不含内部路径或后端细节。

## 范围外

- worker 进程、管道协议与资源上限（SLICE-129）。
- 模型与工具出口中介（SLICE-130）。
- 发布默认层级翻成 `sandboxed`，以及 `in_process` 的平台构建密钥校验（SLICE-129 有后端时再做）。
- Postgres 数据迁移；历史记录按缺省读取。
- 控制台的层级展示与切换 UI。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-128-execution-tier.txt`
