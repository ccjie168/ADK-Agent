# ADR-0046 Agent 运行时端口与 ADK 隔离

状态: Accepted   日期: 2026-11-28   签字: 用户（会话确认，2026-11-28）

## 背景

平台的执行、入口与组合都直接依赖 Google ADK。耦合点集中在几处，且有两处依赖 ADK 非公开行为：

- `runtime/audit_proxy.py` 用 `__class__` 属性伪造类型，才能通过 ADK A2A 执行器的
  `isinstance(runner, Runner)` 检查。
- `mcp/server.py` 直接使用 `google.adk.dependencies._mcp` 与
  `_agent_to_mcp` 里的 `_build_runner`、`_run_agent`、`_reap_orphaned_sessions`。
- `a2a.py`、`compose/`、`factory.py`、`registry/loader.py`、`models/gateway_llm.py`
  直接 import ADK 类型。

风险不在“用了 ADK”，而在升级时的爆炸半径不可控：每次升级都要人工读源码找这类技巧，
没有机械化的检查。平台自有资产（`orchestration/`、审计、审批、配额、工具网关）反而不
依赖 ADK，说明隔离是可行的。

## 决定

1. **引入运行时端口**：平台用自己的类型描述一次运行（已有 `Invocation`、
   `InvocationResult`、`AgentRef`），新增 `AgentRuntime` 端口：
   `load(path) -> agent` 与 `run(agent, invocation) -> InvocationResult`。
   ADK 只是该端口的一个实现。
2. **单一适配层**：新增 `src/adk_agent/adapters/adk/`，只有该目录可以 import
   `google.adk`。用 import-linter 契约强制，违反即红。
3. **去掉类型伪造**：`AuditedRunner` 改成显式能力接口（例如 `runs()` 或
   `is_agent_runner()`），A2A 执行器侧由适配层提供包装，不再依赖 `__class__`。
4. **事件与模型边界**：ADK 的 `Event`、`LlmResponse`、`Content` 在适配层一次性转换成
   平台类型；上层不出现 ADK 类型标注。
5. **兼容演练**：新增 `scripts/adk_compat.py`，检查被依赖的 ADK 面（`Runner.run_async`
   签名、`Event` 字段、`FastMCP` 工厂、A2A 执行器的门控方式、`_agent_to_mcp` 辅助
   函数），在 CI 与升级前运行；任何一项漂移立即失败，并给出复核清单。
6. **版本策略**：保持 `google-adk>=2,<3` 的 pin；升级必须三件套：演练通过、`--full`
   门禁通过、在本 ADR 的升级记录里写明复核结论。
7. **不 fork、不迁移**：不复制 ADK 源码，也不换成其他 agent 框架；本 ADR 只解决隔离
   与可维护性。

## 切片

1. **0046-1 端口与导入墙**：`AgentRuntime` 端口、`adapters/adk/` 骨架、AST 导入墙
   （`scripts/adk_wall.py`，接到 layering 步）、`scripts/adk_compat.py` 与对应用例。
   行为不变。
2. **0046-2a 入口与运行能力**：`mcp/server.py`、`a2a.py`、`console`/`serve` 的加载与
   运行改走适配层；`AuditedRunner` 的类型伪造替换为显式能力检查。行为等价，靠现有集成
   用例兜底。做完这一刀，运行时路径的墙是真的。
3. **0046-2b 事件边界**：定义平台的运行事件类型，在适配层转换；上层不再出现 ADK 的
   `Event`。与 2a 分开验证，回滚互不影响。
4. **0046-3 加载与组合迁移**：`registry/loader.py`、`compose/`、`factory.py`、
   `models/gateway_llm.py` 收进适配层；补 ADK 升级手册。

## 后果

- 升级 ADK 的成本从「读源码找技巧」变成「跑演练 + 看清单」。
- 上层测试不再需要 ADK 类型，纯函数与端口更易测。
- 迁移期会有一次性的机械改动，触及 MCP/A2A/加载/组合多条路径，回归面较大。
- 仍然依赖 ADK 的语义（会话、事件流），只是把依赖关进一扇门。

## 验收

- `import-linter` 契约：除 `adapters/adk/` 外没有任何模块 import `google.adk`。
- `scripts/adk_compat.py` 在 CI 与本地通过，故意改坏 pin 时能红。
- `AuditedRunner` 不再实现 `__class__`；A2A 与 MCP 路径的现有用例全部通过。
- 升级到下一个 ADK 次版本时，演练 + 门禁给出明确结论，不需要读 ADK 源码。

## 风险与回滚

- 风险：迁移触及入口与加载，可能引入行为差异；ADK 内部辅助函数在次版本间仍可能变化，
  演练只能降低概率。
- 回滚：适配层是新增结构，可逐切片回退；端口与实现同 PR 交付，不保留双份路径。

## 替代方案

- **继续现状**：升级时继续靠人工读源码，风险随版本累积，不选。
- **迁移到自研循环或其他框架**：代价大、丢掉 A2A 与 Gemini 生态对齐，不选。

## 与其他 ADR 的关系

在本 ADR 之后：ADR-0047（连接器与插件加载）复用这里定的适配层边界。

## 升级记录

每次升级 `google-adk` 的次版本都在这里加一行：版本、日期、`scripts/adk_compat.py`
结果、`python scripts/check.py --full` 结果、人工复核结论。步骤见
`docs/guides/adk-upgrade.md`。当前记录：

| ADK 版本 | 日期 | 演练 | 门禁 | 复核结论 |
| --- | --- | --- | --- | --- |
| 2.14.0 | 2026-11-28 | ALL PASS（六项） | ALL PASS | 首次收口到空基线，无漂移 |
