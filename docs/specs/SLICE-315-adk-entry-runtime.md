# SLICE-315 入口与运行时改走适配层（ADR-0046 切片 2a）

状态: active
依据: ADR-0046 已确认（2026-11-28）

## 意图

把 MCP、A2A、控制台、CLI 与运行时用到的 ADK 面全部收进 `adk_agent.adapters.adk`，
并去掉 `AuditedRunner.__class__` 类型伪装。行为等价，靠现有集成用例兜底。

迁移的模块（迁完即从墙的基线里删除）：

- `adk_agent.a2a`：`_to_a2a`、`_remote_a2a_agent`、`_build_runner` 的 ADK 模块路径
  改成适配层函数；`_to_a2a`/`_remote_a2a_agent`/`_import_module` 仍留在 `a2a.py`
  作为测试接缝，内部委托适配层。
- `adk_agent.mcp.server`：`FastMCP`、`Context`、`ServerSession`、`to_mcp_server`、
  `_build_runner`、`_run_agent`、`_reap_orphaned_sessions`、`InMemorySessionService`
  改由 `adapters.adk.mcp` 提供。
- `adk_agent.console`：`BaseLlm`、`BaseAgent`、`Runner`、`InMemorySessionService`。
- `adk_agent.cli`：`Runner`、`InMemorySessionService`。
- `adk_agent.runtime.execution`：`RunConfig` 改为适配层的 `run_config()`。
- `adk_agent.runtime.sessions`：三个 session 服务工厂改由 `adapters.adk.sessions`
  构造；`_import_module` 接缝保留并注入适配层，缺驱动仍抛 `SessionStoreUnavailable`。

类型伪装替换：`AuditedRunner` 删除 `__class__` property；A2A 侧由
`adapters.adk.runner.RunnerFacade`（真正的 `Runner` 子类，行为全部委托给代理）
满足执行器的 `isinstance(runner, Runner)` 门控。

## 契约（先改）

- 无对外接口变化：`adk_agent.a2a`、`adk_agent.mcp.server`、`adk_agent.runtime.sessions`
  的公开名字与错误类型不变，`A2aUnavailable` 仍可从 `adk_agent.a2a` 导入。
- `adapters.adk` 新增导出：`BaseAgent`、`BaseLlm`、`Runner`、`RunnerFacade`、
  `make_runner`、`build_runner`、`run_config`、`in_memory_session_service`、
  `sqlite_session_service`、`database_session_service`，以及 `mcp`、`a2a` 两个子模块。
- 墙的基线从 20 个模块减到 14 个，只留组合与工具侧模块。

## 完成判据

- [ ] 六个入口/运行时模块不再直接 import ADK -> `test_entry_modules_leave_the_wall`
- [ ] 基线只剩组合与工具侧模块 -> `test_baseline_is_only_composition_and_tools`
- [ ] 代理不再伪造类型 -> `test_audited_runner_no_longer_fakes_its_class`
- [ ] 门面是真 `Runner` 且属性与 `run_async` 都委托 -> `test_runner_facade_is_a_real_runner`
- [ ] A2A 交给执行器的是真 `Runner`，内层仍是审计代理 -> `test_a2a_hands_the_executor_a_real_runner`
- [ ] session 工厂走适配层且类型不变 -> `test_session_factories_go_through_the_adapter`
- [ ] 缺 A2A 依赖仍给安装提示 -> 现有 `test_missing_extra_has_install_hint` 通过
- [ ] 缺 session 驱动仍给 `SessionStoreUnavailable` -> 现有 `test_missing_driver_hint` 通过
- [ ] 兼容演练新增门面门控检查 -> `test_adk_compat_drill_checks_the_runner_gate`
- [ ] `--full` 门禁通过

## 反例

实现前：六个模块仍在基线里（`test_entry_modules_leave_the_wall` 红）；
`AuditedRunner.__dict__` 有 `__class__`（红）；`adapters.adk.runner` 不存在
（门面与兼容检查 ImportError）；基线是 20 项（红）。

## 5 问威胁建模

1. **数据**：无新增数据面；session 工厂仍读 `SESSION_URL` 与 `--session-db`。
2. **调用方**：CLI、控制台、MCP/A2A 服务。
3. **信任边界**：适配层是唯一碰 ADK 内部函数（`_build_runner`、`_run_agent`、
   `_reap_orphaned_sessions`）的地方，门控变化由兼容演练发现。
4. **恶意输入**：无新增外部输入；门面只转发已构造的对象。
5. **失败是否泄露信息**：错误类型与文案不变。

## 范围外

- 事件模型（0046-2b）：`runtime/execution.py` 仍消费 ADK `Event`。
- 加载与组合（0046-3）：`registry.loader`、`compose`、`factory`、`models`、
  `sandbox`、`tools`、`triggers_service` 仍在基线。
- `google.genai` 类型不在墙内。

## 证据

- `docs/evidence/SLICE-315-adk-entry-runtime.txt`
