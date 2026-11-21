# SLICE-204 控制台启动引用的检索接线

状态: gated
依据: 2026-11-21 复盘第 4 节第 1 条、PROGRESS 已知缺口第 10 条。

## 意图

1. 用 `--agent-ref` 启动控制台时，从注册表加载的 agent 带上自己的 manifest，因而能按
   `manifest.rag` 构造运行时检索，不再静默跳过。
2. 文件加载（`--agents`）的 agent 仍然没有 manifest，不启用检索；按需加载行为不变。
3. 运维手册的「运行时检索」更新失效说明：启动引用现在生效，只有文件加载不生效。

## 契约（先改）

- 无对外契约变更。`--agent-ref`、`--rag-*` 参数与 manifest 形状都不变；改动只在内部把
  registry 加载结果里的 manifest 随 agent 传到控制台注册路径。
- `docs/guides/operations.md` 的说明属于对外表述，随代码在同一 PR 更正。

## 完成判据

- [x] 注册表加载的 agent 携带 manifest -> `test_registry_ref_agent_carries_its_manifest`
- [x] 控制台启动注册时用该 manifest 构造检索上下文 -> `test_console_startup_agent_gets_rag_context`
- [x] 文件加载的 agent 仍不构造检索上下文 -> `test_console_file_loaded_agent_stays_without_rag`
- [x] 全量门禁通过

## 反例

- [x] 修复前：启动循环 `_register(name, agent)` 不传 manifest，假工厂的 `context()` 不被调用，用例失败。
- [x] 若把 manifest 误用在文件加载路径，第三个用例失败。

## 5 问威胁建模

1. **数据**：agent 的 manifest（含 `rag` 配置与 `tool_grants`）与运行时检索上下文。
2. **调用方**：控制台启动流程与按需加载流程。
3. **信任边界**：注册表记录 → 运行时配置。
4. **恶意输入最坏结果**：把不属于该 agent 的 manifest 挂上去，导致越权检索或错误策略。缓解：manifest
   取自注册表记录本身，随同一次加载返回；不按名字二次查找。
5. **失败是否泄露信息**：无新增输出；检索失败沿用 `on_error` 与既有审计。

## 范围外

- MCP 与 A2A 入口的检索接线。
- `model_allowlist` 是否执行的语义确认。
- 沙箱化触发的检索缺口。

## 证据

- `docs/evidence/SLICE-204-console-startup-rag.txt`
