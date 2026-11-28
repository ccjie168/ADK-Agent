# ADK 升级手册（ADR-0046）

`google-adk` 的 pin 是 `>=2,<3`。升级到新的次版本时按下面的顺序做，任何一步变红就停下来。

## 1. 跑兼容演练

```
python scripts/adk_compat.py
```

六项检查覆盖平台真正依赖的 ADK 面：

| 检查 | 依赖的 ADK 面 | 变红说明 |
| --- | --- | --- |
| `runner` | `Runner.run_async` 的 `new_message`/`user_id`/`session_id` 参数 | 运行入口签名变了 |
| `events` | `Event` 的 `author`/`content`/`invocation_id` 字段与 `is_final_response` 方法 | 事件边界要改，`adapters.adk.events.to_run_event` |
| `mcp` | `google.adk.dependencies._mcp` 的 `FastMCP`/`Context`/`ServerSession` | MCP 出口要改 |
| `agent-to-mcp` | `_agent_to_mcp` 的 `_build_runner`/`_run_agent`/`_reap_orphaned_sessions` | 内部辅助函数变了 |
| `runner-gate` | A2A 执行器的 `isinstance(runner, Runner)` 门控 | `RunnerFacade` 需要重新设计 |
| `a2a-executor` | `A2aAgentExecutor` 仍存在（`a2a-sdk` 缺失时 SKIP） | A2A 入口要改 |

`FAIL` 时先读 `src/adk_agent/adapters/adk/` 里对应的转发函数，再改演练；不要改演练去迁就
实现。

## 2. 跑导入墙与全门禁

```
python scripts/adk_wall.py
python scripts/check.py --full
```

`adk_wall.py` 的基线是空集：任何 `adapters/adk` 之外的 `google.adk` 导入都是违规。
全门禁九步全绿才算通过；`--fast` 不够，`sast` 与 `deps` 也要跑。

## 3. 升级记录

在 `docs/decisions/ADR-0046-adk-isolation.md` 末尾的升级记录里加一行：版本、日期、
演练结果、门禁数字、人工复核结论（哪些线被破过、怎么修的）。没有这条记录不算完成。

## 4. 常见漂移与处理位置

| 症状 | 先看 |
| --- | --- |
| 运行时拿不到最终文本 | `adapters/adk/events.py` 的 `to_run_event` 与兼容演练的 `events` |
| A2A 启动即 `TypeError: Runner must be a Runner instance` | `adapters/adk/runner.py` 的 `RunnerFacade` 与 `runner-gate` |
| MCP 工具调用 500 | `adapters/adk/mcp.py` 的三个内部辅助函数 |
| session 初始化失败 | `adapters/adk/sessions.py` 与 `runtime/sessions.py` 的驱动映射 |
| 模型构造参数不认 | `adapters/adk/models.py` 的四个 provider 构造器 |

## 5. 不要做的事

- 不要在适配层之外直接 import `google.adk`（墙会红）。
- 不要用类型伪装（`__class__` property 等）绕过 ADK 的 isinstance 门控；用适配层的真子类。
- 不要在新代码里继续直接使用 `google.genai` 的 `Content`/`Part`（现有运行时与沙箱
  已有使用，属记录在案的边界外依赖）；新的事件/消息转换放在适配层。
