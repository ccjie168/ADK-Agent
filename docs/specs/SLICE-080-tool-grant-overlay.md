# SLICE-080 运行时合并临时授权

状态: merged
依据: ADR-0011 第 2、5、6 条，SLICE-078，SLICE-079。

## 意图（要什么，不写怎么写）

授权存储有了，守卫也接上了，但运行时还不会查临时授权。这一刀把已批准且未过期的临时授权合并进工具策略，并给三个命令加配置。

- `GrantPolicyEngine` 增加 `overlay: ToolGrantStore | None`：manifest 命中先放行；否则按 invocation 的 agent_ref 查临时授权；命中放行；存储异常拒绝并标记错误码。
- `PolicyDecision` 增加可选 `error_code`，`ToolGuard` 用它写审计（默认仍是 `policy_denied`）。
- `install_declared_guards(agent, audit, overlay=None)` 把 overlay 传给策略引擎。
- `console`、`serve`、`serve-many` 接受 `--tool-grants-dir DIR` 或 `GRANT_URL`，二选一；控制台把 store 传给应用。
- 不做缓存，不做控制台申请界面（SLICE-081）。

## 新增文件

- `tests/test_tool_grant_overlay.py`
- `docs/evidence/SLICE-080-tool-grant-overlay.txt`

## 修改文件

- `src/adk_agent/core/policy.py`
- `src/adk_agent/tools/policy.py`、`tools/guard.py`、`tools/enforcement.py`
- `src/adk_agent/console.py`、`src/adk_agent/cli.py`
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GrantPolicyEngine(grants, *, overlay: ToolGrantStore | None = None)
  tool.call + manifest -> allow (grants-v1)
  tool.call + overlay.active(...) -> allow (grants-v2)
  overlay 抛 GrantStoreError -> deny, error_code=grant_store_unavailable
  其余 -> deny (grants-v1)

PolicyDecision += error_code: str | None = None

_tool_grant_store(args) -> FileToolGrantStore | PostgresToolGrantStore | None
```

## 完成判据（可执行）

- [x] manifest 命中优先，不查存储 -> `tests/test_tool_grant_overlay.py::test_manifest_grant_wins`
- [x] 临时授权命中放行 -> `::test_overlay_grant_allows`
- [x] 未命中拒绝 -> `::test_overlay_miss_denies`
- [x] 存储异常拒绝并报错误码 -> `::test_store_error_denies`
- [x] 端到端经 Runner 执行工具 -> `::test_overlay_allows_through_runner`
- [x] 控制台装配存储 -> `::test_console_wires_grant_store`
- [x] `serve` 装配存储 -> `::test_serve_wires_grant_store`
- [x] `GRANT_URL` 与目录互斥 -> `::test_grant_source_exclusive`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`GrantPolicyEngine([], overlay=...)` -> 当前 `TypeError`
- [x] 反例 2：`console --tool-grants-dir DIR` -> 当前 argparse 退出 2
- [x] 反例 3：临时授权命中仍被拒 -> 当前无合并逻辑

## 契约（如涉及对外接口）

已先改 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：agent_ref、工具名、临时授权、存储错误。
2. **调用方**：MCP 宿主、A2A 消费方、控制台。
3. **信任边界**：策略引擎到共享授权存储。
4. **恶意输入最坏结果**：临时授权跨版本生效（缓解：按 digest 查询）；存储故障时放行（缓解：异常一律拒绝）；过期授权生效（缓解：存储的 active 只看未过期）。
5. **失败是否泄露信息**：拒绝原因固定；审计只写错误码。

## 范围外

- 控制台申请与审批接口（SLICE-081）。
- 授权缓存与实时撤权推送。
- A2A 的临时授权配置（ADR 未列；后续可加）。
- 数据分级强制执行。

## 证据

- 反例红: `docs/evidence/SLICE-080-tool-grant-overlay.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres 授权后经 Runner 放行
