# SLICE-197 运行时 RAG 预取与注入边界

状态: gated
依据: ADR-0036（Accepted 2026-11-20）决定 2-6 / 切片 2。

## 意图

1. `rag/context.py` 新增 `RagContext`：按 manifest 的 `rag` 配置做一次检索，经 `RagGuard` 过滤后渲染
   固定边界的上下文块；没有引用时返回空串。
2. `on_error`：`deny`（默认）抛 `RagUnavailable` 让本次运行失败；`degrade` 记一条警告后返回空串继续。
3. `AgentRuntime` 增加可选 `rag` 参数，预取得到的块拼在用户消息之前；`invocation.input` 保持原样，
   审计与结果身份仍用原始输入。
4. 引用按 `top_k` 截断，块内的编号、来源与置信度由平台渲染，片段内容不参与指令。

## 契约（先改）

- `docs/contracts/rag_service.md` 增加「运行时注入（ADR-0036）」一节：注入块格式、`on_error` 语义、
  `top_k` 截断、`invocation.input` 不变。

## 完成判据

- [x] 有引用时渲染编号、来源与置信度 -> `test_rag_context_renders_citations`
- [x] 没有引用时返回空串 -> `test_rag_context_returns_empty_without_citations`
- [x] 注入模式片段被 `RagGuard` 过滤 -> `test_rag_context_drops_injected_snippet`
- [x] 超过 `top_k` 的引用被截断 -> `test_rag_context_truncates_to_top_k`
- [x] `deny` 下存储失败抛 `RagUnavailable` -> `test_rag_context_deny_raises_on_failure`
- [x] `degrade` 下存储失败返回空串 -> `test_rag_context_degrade_returns_empty`
- [x] 运行时把块拼在用户消息前 -> `test_runtime_prefixes_retrieved_context`
- [x] 运行时保留原始 `invocation.input` -> `test_runtime_keeps_original_input`
- [x] 全量门禁通过

## 反例

- [x] 基线 `adk_agent.rag` 没有 `RagContext`，测试收集即 ImportError
- [x] 基线 `AgentRuntime` 没有 `rag` 参数，传入会 TypeError
- [x] 不截断时 `top_k=1` 仍会注入两条引用（用假检索器构造两条验证）

## 5 问威胁建模

1. **数据**：检索片段进入模型上下文；`source_id` 与置信度进入注入块。
2. **调用方**：运行任一打开了 `rag.enabled` 的 agent 的调用方。
3. **信任边界**：检索存储 → 模型上下文；principal 的 ACL → 可见片段。
4. **恶意输入最坏结果**：库里被塞入「忽略之前的指令」类片段，或片段试图伪造边界标记提前关闭上下文块。
   缓解：`RagGuard` 在注入前过滤已知注入模式；渲染时对片段中的 `<retrieved_context>` / `</retrieved_context>`
   字面量做转义，防止伪造边界；块只放在用户消息最前面，不进入系统指令。
5. **失败是否泄露信息**：`RagUnavailable` 只带异常类型；警告日志不含片段正文。

## 范围外

- `rag.retrieve` 审计与预算接线（切片 3）。
- 控制台、MCP、A2A、触发的 CLI 接线（切片 4）。
- 重排与多轮检索改写。

## 证据

- `docs/evidence/SLICE-197-rag-runtime-prefetch.txt`
