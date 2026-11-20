# ADR-0036 RAG 检索接入 agent 运行路径

状态: Accepted   日期: 2026-11-20   签字: Jie CAO（会话确认）

## 背景

ADR-0032 定义了 `RagService` 端口与 `Citation`（含 `acl_checked`），ADR-0035 交付了 pgvector 存储、
嵌入网关、摄取管线与检索服务，SLICE-194/195 又把摄取与检索接到 CLI。但运行路径没有消费方：
`AgentRuntime` 与 `AuditedRunner` 都不调用 `RagService`，任何已发布的 agent 都拿不到检索结果。

问题不是"怎么检索"，而是**检索在运行路径里如何被触发、结果如何进入上下文、失败如何处理**。这三件事
决定了成本、提示注入面与越权面，必须在写代码前定下来。

## 决定

1. **显式启用，按 manifest 配置。** `AgentManifest` 新增可选 `rag` 块：
   `{"enabled": true, "top_k": 5, "min_confidence": 0.5, "data_classes": [...]}`。
   没有该块或 `enabled=false` 时运行路径完全不变；存量 manifest 的 digest 不受影响（缺省字段从摘要
   载荷里剔除，沿用 `execution_tier`、`model_alias` 的做法）。
2. **运行时预取，不做隐式工具。** 打开 `rag.enabled` 后，运行时在调用模型之前用本次输入做一次检索，
   把结果作为受边界标记的上下文块拼进给模型的指令。不让模型自己决定是否检索，避免"该检索时没检索"
   与工具调用成本不可控。需要模型自主检索的形态留给后续 ADR。
3. **ACL 取自已认证 principal。** 检索用 `invocation.principal` 的租户与 subject，`data_classes` 取
   `rag.data_classes`（缺省空列表）。返回的引用一律 `acl_checked=True`；principal 缺租户或检索器抛
   `RagStoreUnavailable` 时 fail-closed，不注入任何上下文。
4. **失败策略可选，默认 fail-closed。** `rag.on_error` 取 `"deny"`（默认）或 `"degrade"`。
   `deny` 让本次运行以 `rag_unavailable` 失败；`degrade` 记一条 `rag.retrieve` 失败审计后继续运行，
   不注入上下文。两种模式都写审计，`degrade` 需要显式声明，等于一次安全风险接受。
5. **成本与预算走同一通道。** 查询嵌入经 `EmbeddingGateway` 与运行共用的 `BudgetTracker`；预算超限
   按第 4 条的失败策略处理，不绕过预算。
6. **注入边界固定。** 上下文块的形态由平台渲染：固定分隔符、每条引用带 `source_id` 与置信度、
   `RagGuard` 在注入前过滤低置信度与提示注入引用。agent 指令不能改写这个边界，渲染结果不进入审计。
7. **审计一条 `rag.retrieve`。** 字段：租户、run、agent、`top_k`、返回条数、被过滤条数、状态与
   `error_code`；不记查询原文、片段或置信度明细，避免把语料写进审计链。

## 备选与否决

- **把检索暴露成工具让模型调用。** 更灵活、按需计费，但需要工具网关侧的新工具与授权模型，且"该检索
  而没检索"无法在平台侧保证。留作后续 ADR。
- **每个 run 无条件预取。** 简单，但闲聊类请求也要付 embedding 与上下文开销，并放大注入面。否决。
- **失败时静默降级为无上下文。** 会让"检索坏了"看起来像"没有相关资料"，运维无法察觉。否决默认值，
  只保留显式 `on_error="degrade"`。
- **把检索放在模型网关里。** 网关看不到 agent 指令语义，也无法按 manifest 配置；且会把 RAG 责任混进
  一个只做转发与策略的服务。否决。

## 后果

- 运行路径多一次模型调用（查询嵌入），成本可见于 `model.embed` 与 `rag.retrieve` 两条审计。
- 沙箱执行：检索在父进程完成，注入的是文本，不改变 ADR-0024 的边界；沙箱 agent 与 in-process agent
  走同一注入路径。
- 存量 manifest 不受影响；新发布可以显式打开。控制台与注册表面板需要后续切片展示 `rag` 配置。
- `degrade` 是显式的安全风险接受，需在运维手册写明：检索故障时 agent 会在无资料的情况下回答。

## 确认记录（2026-11-20 会话确认）

1. 预取时机：只用本次 `input` 做一次检索，不追溯多轮历史提问。
2. `on_error` 默认值：`deny`（fail-closed），`degrade` 必须显式声明。
3. `rag.data_classes`：允许缺省为空列表，发布时不强制声明；缺省等于只命中未分级分块。

## 切片（确认后分配）

1. `AgentManifest.rag` 块与 digest 向后兼容，重生成 manifest 契约。
2. 运行时预取与注入边界（`RagGuard` + 固定分隔符），`on_error` 两种语义。
3. `rag.retrieve` 审计与预算接线。
4. 运维手册与使用手册更新，控制台展示 `rag` 配置（如需要）。
