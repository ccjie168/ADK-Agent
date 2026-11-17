# SLICE-131 沙箱执行接入：触发服务与平台门槛

状态: gated
依据: ADR-0024 第 2、5 条。把 `sandboxed` 记录真正接到一条执行路径上，先做触发服务；其他面继续拒绝，避免注册后端后仍走进程内加载。

## 意图（要什么，不写怎么写）

1. `serve-triggers` 新增 `--agent-sandbox`：父进程构造 `ProcessAgentSandbox(model=build_model())` 并注入触发服务。
2. 平台门槛：非 POSIX 默认拒绝，必须显式 `--allow-unsandboxed` 才允许本地开发，启动时在 stderr 提示降级。
3. `sandboxed` 触发的执行：摘要、生命周期、审批检查照旧；不加载进程内 agent，取工件字节后调用 `sandbox.run`。
4. 配额用 `quota.reserve` 包住；写 `agent.run` 审计与运行指标；`trigger.fire` 审计照旧。
5. Fail-closed：声明了 `tool_grants` 的 `sandboxed` 记录拒绝执行（工具中介还没做）；没有注入沙箱返回 `sandbox_unavailable`。
6. 不在生产进程里调用 `set_agent_sandbox_backend`；控制台与 `--agent-ref` 加载路径继续拒绝 `sandboxed`。

## 数据形状

- `sandbox/agent_process.py`：`agent_sandbox_supported() -> bool`，POSIX 为真，Windows 为假。
- `triggers_service.build_triggers_app(..., sandbox: AgentSandboxBackend | None = None)`。
- 触发执行分支：`published.manifest.execution_tier == "sandboxed"` 时走沙箱，否则走现有进程内路径。
- 错误码：`tool_mediation_unavailable` 409；`sandbox_timeout`、`sandbox_crashed`、`sandbox_violation` 均 500。

## 契约（先改）

- `docs/contracts/trigger_service.md`：新增错误码与沙箱执行语义。
- `docs/contracts/cli.md`：`serve-triggers` 的 `--agent-sandbox`、`--allow-unsandboxed`。
- `docs/contracts/sandbox.md`：说明触发路径的注入方式与工具授权拒绝。

## 新增/修改文件

- 修改 `src/adk_agent/triggers_service.py`、`src/adk_agent/cli.py`、`src/adk_agent/sandbox/agent_process.py`
- 扩展 `tests/test_triggers_service.py`
- 文档：上述契约、`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-131-sandbox-execution.txt`

## 完成判据（可执行）

- [x] 注入假沙箱后，`sandboxed` 触发返回沙箱文本 -> `tests/test_triggers_service.py::test_sandboxed_trigger_uses_the_backend`
- [x] 沙箱调用收到工件字节与触发输入 -> 同上用例检查记录
- [x] 写 `agent.run` 审计，status=ok -> 同上
- [x] 声明 `tool_grants` 的 `sandboxed` 触发 409 `tool_mediation_unavailable` -> `::test_sandboxed_tool_grants_are_refused`
- [x] 未注入沙箱 409 `sandbox_unavailable` -> `tests/test_triggers_service.py::test_sandboxed_trigger_is_refused`
- [x] 沙箱超时映射 500 `sandbox_timeout` -> `::test_sandbox_timeout_is_mapped`
- [x] 非 POSIX 未加 `--allow-unsandboxed` 启动失败 -> `tests/test_triggers_service.py::test_floor_rejects_missing_posix_limits`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：`sandboxed` 触发照旧走进程内加载 -> 期望 `::test_sandboxed_trigger_uses_the_backend` 失败
- [x] 反例 2：带工具授权的 `sandboxed` 触发被执行 -> 期望 `::test_sandboxed_tool_grants_are_refused` 失败
- [x] 反例 3：Windows 上未加覆盖也能启用沙箱 -> 期望 `::test_floor_rejects_windows_without_override` 失败

## 5 问威胁建模（10 分钟）

1. **数据**：工件字节、触发输入、沙箱文本、审计事件、配额键。
2. **调用方**：webhook 与调度器进入触发服务；沙箱由服务启动参数注入。
3. **信任边界**：触发服务到子进程；父进程模型；工件存储。
4. **恶意输入最坏结果**：声明工具绕过授权（缓解：有 `tool_grants` 的 `sandboxed` 记录直接拒绝，工具中介落地前不执行）；Windows 上无隔离运行（缓解：默认拒绝，需显式覆盖并提示）；沙箱崩溃拖垮服务（缓解：超时与进程组回收，错误映射为 500）；配额绕过（缓解：`quota.reserve` 包住整次运行）。
5. **失败是否泄露信息**：错误只含稳定错误码；沙箱异常只回类名。

## 范围外

- 控制台、A2A 与 `--agent-ref` 的远程 agent 适配（下一片）。
- 工具网关 RPC 与工具授权执行。
- `in_process` 的构建密钥校验与 publish 默认层级翻转（下一片）。
- 模型策略校验与用量计费。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-131-sandbox-execution.txt`
