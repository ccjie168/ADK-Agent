# SLICE-206 MCP 与 A2A 的检索接线

状态: gated
依据: PROGRESS 已知缺口第 9 与第 10 条、2026-11-21 复盘第七节第 3 条。

## 意图

1. `serve`、`serve-many` 与 `serve-a2a` 接受 `--rag-*`，对 `--agent-ref` 加载且 manifest
   `rag.enabled=true` 的记录做运行时预取与 `rag.retrieve` 审计，与 `console` 语义一致。
2. 文件加载的 `--agent`/`--agents` 没有 manifest，仍然不检索。
3. 检索失败按 `on_error` 处理：`deny` 让本次运行失败并写 `agent.run` error 审计；`degrade` 继续。
4. `docs/contracts/cli.md` 先记录新参数与生效范围。

## 契约（先改）

- `docs/contracts/cli.md` 新增「`serve` / `serve-many` / `serve-a2a` 的运行时检索（ADR-0036）」一节。
- manifest 与审计事件形状不变；`rag.retrieve` 沿用既有计数与状态字段。

## 完成判据

- [x] 预取块拼到 MCP/A2A 运行的首条消息 -> `test_retrieval_block_is_prepended_to_new_message`
- [x] 检索失败审计 `agent.run` error 且不调用 agent -> `test_retrieval_failure_is_audited_and_skips_the_agent`
- [x] 未配置检索时消息原样 -> `test_no_rag_keeps_the_message_unchanged`
- [x] 只给 rag 也会包一层审计代理 -> `test_wrap_runner_wraps_when_only_rag_is_set`
- [x] 三个命令的 help 列出 `--rag-*` -> `test_serve_modes_help_list_rag_flags`
- [x] 注册表 manifest 决定是否检索，文件加载跳过 -> `test_agent_rag_uses_the_registry_manifest`
- [x] 只给 rag 的 A2A 调用也会包 runner -> `test_a2a_wraps_runner_when_only_rag_is_set`
- [x] 全量门禁通过

## 反例

- [x] 基线：`wrap_runner` 不认识 `rag`，前四类用例失败；help 没有 `--rag-*`。
- [x] 若把文件加载也接上检索，`test_agent_rag_skips_file_loaded_agents_and_missing_factory` 失败。

## 5 问威胁建模

1. **数据**：检索上下文、manifest 的 `rag` 配置与审计事件。
2. **调用方**：MCP 主机与 A2A peer。
3. **信任边界**：注册表记录 → 运行时检索；外部调用方 → MCP/A2A 入口。
4. **恶意输入最坏结果**：把检索内容注入到不该看到的租户，或让检索静默失败。缓解：主体租户来自
   认证（MCP principal / A2A peer），ACL 在 `PgVectorRagService` 内执行；失败按 `on_error` 显式处理并
   审计；文件加载没有 manifest 不检索。
5. **失败是否泄露信息**：审计只记计数、状态与延迟，不含查询与片段；与 console 同一实现。

## 范围外

- 沙箱化触发（`execution_tier=sandboxed`）的检索缺口。
- 检索重排与查询改写。

## 证据

- `docs/evidence/SLICE-206-mcp-a2a-rag.txt`
