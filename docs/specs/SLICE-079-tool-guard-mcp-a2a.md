# SLICE-079 MCP 与 A2A 的工具授权

状态: merged
依据: ADR-0011 背景与第 2 条，SLICE-020，SLICE-046。

## 意图（要什么，不写怎么写）

控制台会安装 `ToolGuard`，MCP 与 A2A 不会。也就是说这两个入口下 agent 可以调用任何工具，manifest 的 `tool_grants` 形同虚设。这一刀把守卫接到两个运行路径，并给运行时补上 invocation 上下文。

- 新增 `tools/enforcement.py`：`declared_tool_ids`、`install_declared_guards`，控制台改用同一实现。
- 按引用加载的 agent 带上 manifest 授权（`_adk_tool_grants`），守卫优先使用它；否则用 agent 树声明的工具。
- `AuditedRunner` 在运行期间设置 invocation 上下文；`wrap_runner` 支持 `require_context`，即使没有审计也包装。
- `serve_agent`、`serve_many`、`serve_a2a` 接受工具授权开关，由 CLI 在启动时开启。
- 不改临时授权合并；那是 SLICE-080。

## 新增文件

- `src/adk_agent/tools/enforcement.py`
- `tests/test_tool_guard_mcp.py`
- `docs/evidence/SLICE-079-tool-guard-mcp-a2a.txt`

## 修改文件

- `src/adk_agent/tools/guard.py`、`tools/__init__.py`
- `src/adk_agent/runtime/audit_proxy.py`、`registry/refs.py`
- `src/adk_agent/console.py`
- `src/adk_agent/mcp/server.py`、`a2a.py`、`cli.py`
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
install_declared_guards(agent, audit) -> None
  授权 = getattr(agent, "_adk_tool_grants", None) or declared_tool_ids(agent)

wrap_runner(..., require_context=False)
require_context=True 时即使 audit/quota/metrics 都为空也返回 AuditedRunner

AuditedRunner.run_async 期间 set_invocation(Invocation(...))，结束后 reset
```

## 完成判据（可执行）

- [x] 声明的工具可调用 -> `tests/test_tool_guard_mcp.py::test_declared_tool_runs`
- [x] 未声明的工具被拒且不执行 -> `::test_undeclared_tool_is_denied`
- [x] 无审计时也设置上下文 -> `::test_require_context_without_audit`
- [x] `serve` 安装守卫 -> `::test_cli_serve_installs_guard`
- [x] `serve-many` 安装守卫 -> `::test_cli_serve_many_installs_guards`
- [x] `serve-a2a` 安装守卫并传开关 -> `::test_cli_a2a_installs_guard`
- [x] manifest 授权优先于声明工具 -> `::test_manifest_grants_override_declared_tools`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：未声明工具经 Runner 调用成功 -> 当前无守卫，工具会执行
- [x] 反例 2：`wrap_runner(require_context=True)` 返回原对象 -> 当前不认这个参数
- [x] 反例 3：`serve_agent(..., tool_guard=True)` -> 当前 `TypeError`

## 契约（如涉及对外接口）

已先改 `docs/contracts/cli.md` 的工具授权一节。

## 5 问威胁建模（10 分钟）

1. **数据**：工具名、调用参数、拒绝结果、manifest 授权。
2. **调用方**：MCP 宿主、A2A 消费方、控制台。
3. **信任边界**：模型生成的工具调用到工具执行；运行进程到策略。
4. **恶意输入最坏结果**：模型调用未授权工具造成越权（缓解：守卫清单默认拒绝）；守卫因缺少上下文直接放行（缓解：`require_context` 强制包装并在缺失时抛错）；审计缺失时静默放行（缓解：拦截不依赖审计）。
5. **失败是否泄露信息**：拒绝结果是固定结构；审计只记工具名与参数哈希。

## 范围外

- 临时授权合并（SLICE-080）。
- 控制台授权申请与审批界面（SLICE-081）。
- 工具级数据分级强制执行。
- stdio 之外的 MCP 新传输。

## 证据

- 反例红: `docs/evidence/SLICE-079-tool-guard-mcp-a2a.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，ScriptedLlm 经 Runner 的端到端拒绝
