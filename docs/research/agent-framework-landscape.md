# Agent 框架与 UI 参考调研

状态: 调研记录
日期: 2026-11-15
方法: GitHub API 读取仓库元数据与 README，星数只作方向参考。
范围: 与当前 ADK 平台同层或可复用的开源项目，不含闭源产品。

## 结论

1. 当前 ADK 的差异化不在 agent 框架层，而在治理控制面：签名工件、注册表与市场、租户隔离、工具授权、审批、审计哈希链、配额与发布流水线。这些能力大多数开源框架没有组合到一起。
2. 最值得补的五项是持久化执行、OTel 可观测、内容护栏、评测深度和沙箱隔离。它们决定平台能否从内部试点走到生产。
3. UI 不应重造 Dify 或 Langfuse。聊天页参考 Open WebUI 与 LibreChat，运行详情参考 Langfuse 与 Phoenix，审批参考 LangChain Agent Inbox，镜像与目录参考 Harbor 与 Backstage。

## 一、项目地图

### 1.1 Agent 框架

| 项目 | 星数 | 擅长 | 可借鉴 |
| --- | --- | --- | --- |
| [google/adk-python](https://github.com/google/adk-python) | 22.2k | 图运行时、Task API、tool confirmation、eval、dev UI | 官方 eval 与开发 UI 的交互 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 45.0k | durable execution、HITL interrupt、长期记忆、Studio | 检查点、恢复与 interrupt 语义 |
| [microsoft/agent-framework](https://github.com/microsoft/agent-framework) | 14.7k | 图工作流、checkpoint、time travel、OTel、DevUI | 图编排与时间旅行 |
| [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | 30.7k | 轻量 handoff、guardrails、tracing、sessions | guardrails 与 tracing 的接入方式 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 21.2k | 类型化、OTel、evals、九种 durable 引擎、deferred tools | 类型化契约与 durable 适配器 |
| [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | 60.9k | Crews 角色协作、Flows、控制面 | 角色化编排的表达力 |
| [agno-agi/agno](https://github.com/agno-agi/agno) | 43.2k | memory、knowledge、teams、内置 UI | 记忆与知识层 |
| [strands-agents/harness-sdk](https://github.com/strands-agents/harness-sdk) | 9.2k | 模型无关、hooks、guardrails、steering | 可拦截的 agent loop |

### 1.2 可观测、评测与网关

| 项目 | 星数 | 擅长 | 可借鉴 |
| --- | --- | --- | --- |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | 37.4k | OTel trace、session、prompt 管理、eval、dataset、dashboard | 直接接 OTel，复用 trace 与 eval UI |
| [Arize-ai/phoenix](https://github.com/Arize-ai/phoenix) | 12.3k | OTel tracing、eval、dataset、experiment、playground | 自托管 trace 与实验 |
| [promptfoo/promptfoo](https://github.com/promptfoo/promptfoo) | 27.2k | 评测、红队、模型对比、CI | 红队与回归评测接入发布门禁 |
| [confident-ai/deepeval](https://github.com/confident-ai/deepeval) | 19.5k | Agent 轨迹评测、步骤级指标、合成数据 | 轨迹级评测 |
| [guardrails-ai/guardrails](https://github.com/guardrails-ai/guardrails) | 7.6k | 输入输出校验、结构化输出 | 可插拔校验器 |
| [NVIDIA-NeMo/Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) | 7.5k | 可编程对话护栏、话题控制 | 对话级安全策略 |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 63.3k | 虚拟 key、预算、负载均衡、guardrails、管理面板 | 预算、回退与成本治理 |
| [IBM/mcp-context-forge](https://github.com/IBM/mcp-context-forge) | 4.8k | MCP/A2A/REST 统一网关、注册发现、OTel | 网关与注册表标准化 |
| [archestra-ai/archestra](https://github.com/archestra-ai/archestra) | 4.4k | MCP registry、gateway、guardrails、RAG、SSO、egress | 企业组件的组合方式 |

### 1.3 沙箱、持久化与目录

| 项目 | 星数 | 擅长 | 可借鉴 |
| --- | --- | --- | --- |
| [e2b-dev/E2B](https://github.com/e2b-dev/E2B) | 14.9k | 微虚拟机沙箱、代码执行 | 高风险工具调用的强隔离 |
| [temporalio/temporal](https://github.com/temporalio/temporal) | 24.4k | 持久化工作流、重试、signal/query | 长流程与审批恢复 |
| [conductor-oss/conductor](https://github.com/conductor-oss/conductor) | 32.5k | 事件驱动持久化工作流 | 工作流引擎替代方案 |
| [dbos-inc/dbos-transact-py](https://github.com/dbos-inc/dbos-transact-py) | 1.7k | 数据库支撑的 durable Python 工作流 | 用 Postgres 做检查点 |
| [backstage/backstage](https://github.com/backstage/backstage) | 34.9k | 软件目录、模板、TechDocs、插件 | Agent 目录与所有权 |
| [goharbor/harbor](https://github.com/goharbor/harbor) | 29.7k | 项目、工件、digest、扫描、RBAC、复制 | 镜像仓库的治理与 UI |

### 1.4 可视化与聊天 UI

| 项目 | 星数 | 擅长 | 可借鉴 |
| --- | --- | --- | --- |
| [open-webui/open-webui](https://github.com/open-webui/open-webui) | 158.7k | 聊天、模型切换、知识库、管理面板、主题、i18n | 聊天页与个人偏好 |
| [LibreChat-AI/LibreChat](https://github.com/LibreChat-AI/LibreChat) | 47.1k | 工具活动、reasoning UI、Trace Viewer、可恢复流、上下文用量 | 运行详情与流式体验 |
| [langgenius/dify](https://github.com/langgenius/dify) | 161.2k | App Studio、工作流画布、Prompt IDE、日志、数据集、市场 | 构建侧信息架构 |
| [langflow-ai/langflow](https://github.com/langflow-ai/langflow) | 156.7k | 可视化编排、playground、导出 MCP server | 只读流程图与实时试跑 |
| [FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise) | 55.6k | 可视化 agent 与工具编排 | 画布交互 |
| [langchain-ai/agent-inbox](https://github.com/langchain-ai/agent-inbox) | 1.1k | HITL 收件箱，accept/edit/ignore/response | 审批交互模型 |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) | 13.2k | React 聊天组件 | 聊天前端 |
| [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | 128.2k | 可组合、可访问的组件 | 设计系统底座 |
| [refinedev/refine](https://github.com/refinedev/refine) | 36.0k | 内部工具与管理面板 | 表格、筛选、表单 |

## 二、ADK 现状与缺口

已有，且相对多数开源项目更完整：

- 不可变版本、签名工件、生命周期、评测门禁、市场与按需加载。
- 模型网关、工具网关、连接器出站策略、工具临时授权与审批。
- RBAC、OIDC、四张会话表 RLS、按租户配额与限流。
- 租户审计哈希链、HMAC、密钥轮换、审批收件箱与归档。
- 多副本清单、备份恢复、依赖锁、镜像扫描、SBOM、digest 发布。

缺口，按影响排序：

1. 持久化执行。重试、超时、取消和审批已有，但进程重启后运行状态丢失。
2. OTel 可观测。审计链适合合规，不适合调试；缺 span、瀑布与跨服务关联。
3. 内容护栏。工具策略与 RBAC 不等于输入输出安全，缺 PII 与提示注入防护。
4. 评测深度。有确定性评测与发布门禁，缺数据集、实验对比、LLM as judge、红队。
5. 沙箱强度。有资源与网络限制，不是 microVM 或容器级隔离。
6. 记忆与知识。缺租户隔离的知识库、引用与检索审计。
7. 成本治理。有 token 与成本审计，缺按 agent/provider 的预算、回退与虚拟 key。
8. 目录标准。注册表是自定义格式，缺少 A2A card、MCP catalog、Backstage 式的所有权模型。

## 三、增强建议

### P0

1. **OTel 导出与 trace 瀑布**
   - 给 `agent.run`、`model.call`、`tool.call`、`a2a.call` 产生 span，带 GenAI 语义属性、租户、run、trace 标识。
   - OTLP endpoint 可配置，默认关闭；导出失败不影响运行。
   - 审计链保留，可观测与合规证据分开。
   - 先决条件: 新依赖需要 ADR-0021。

2. **运行检查点与恢复**
   - 运行状态、步骤结果、待审批点存 Postgres，进程重启后从断点继续。
   - 审批从收件箱消息升级为可恢复的 interrupt。
   - 工具调用带幂等键，重放不重复执行。
   - 看板: SLICE-111。

3. **护栏管线**
   - 输入过滤、输出过滤、PII 脱敏、提示注入检测，失败即拒绝。
   - 所有决定进审计，不记录原文。
   - 先做内置规则，不引入新依赖。
   - 看板: SLICE-112。

### P1

4. 评测 2.0。数据集、版本对比、LLM as judge、回归趋势、红队。可接 Promptfoo 或 DeepEval。
5. 预算与回退。按租户、agent、provider 的预算，超限拒绝，provider 故障回退。参考 LiteLLM。
6. 沙箱隔离。高风险工具调用进 E2B 或 microVM，限制 CPU、内存、网络和生命周期。
7. 知识库与记忆。租户隔离的文档与向量存储，回答带引用，检索与写入进审计。

### P2

8. 只读计划图，用 React Flow 展示步骤、状态与审批点，暂不做可视化编辑。
9. 注册表标准化。A2A agent card、MCP server 目录、Backstage 目录、OCI 工件。
10. 策略即代码。Cedar 或 OPA 评估工具与 agent 动作，策略可测试、可版本化。
11. 审计与审批表 RLS、保留与 GC。
12. 可恢复的 SSE 流。

## 四、UI 参考与改造

### 4.1 参考对象

| 参考 | 可借鉴的具体做法 | 用在 ADK 哪一页 |
| --- | --- | --- |
| Open WebUI | 模型切换、知识库、管理面板、主题、i18n、PWA | Chat 与个人偏好 |
| LibreChat | 统一工具活动、reasoning UI、Trace Viewer、可恢复流、上下文用量 | Chat、Runs |
| Dify | App Studio、Prompt IDE、日志与标注、数据集、市场 | 构建侧导航 |
| Langflow | 可视化编排、playground、MCP server 导出 | 只读计划图 |
| Langfuse | OTel 瀑布、session、用户、prompt 管理、eval、dataset、dashboard | Trace 与评测 |
| Phoenix | OTel tracing、eval、dataset、experiment、playground | 自托管可观测 |
| Agent Inbox | accept、edit、ignore、response 四种 HITL 动作 | Approvals |
| Temporal UI | 事件历史、工作流状态、重试、堆栈 | Run 详情 |
| Harbor | 项目、工件、tag 与 digest、扫描结果、RBAC、复制 | Registry |
| Backstage | 目录、所有权、模板、TechDocs | Registry 与文档 |

### 4.2 具体改造

1. **应用外壳**。左侧三组导航：运营（概览、Runs、Sessions、Approvals、Grants）、构建（Registry、Tools、Connectors、Peers）、治理（Policy、Audit、Settings）。顶栏放租户切换、环境标识、全局搜索、主题与用户菜单。支持深链接与面包屑。
2. **登录**。前端加 OIDC PKCE 登录与会话 cookie，保留粘贴 token 的开发模式。
3. **概览页**。运行数、错误率、p95 延迟、成本、待审批、审计链状态、即将到期的授权。
4. **运行详情**。左侧 span 瀑布，显示模型、工具、审批、重试与耗时；右侧 token、成本、状态、审计事件与 trace 关联。参考 Langfuse 与 LibreChat。
5. **市场**。卡片展示版本、digest、签名、评测分数、生命周期、所有者；支持版本对比、加载与卸载。参考 Harbor 与 Backstage。
6. **审批**。上下文、可编辑参数、理由、SLA 倒计时、键盘快捷键、批量处理。参考 Agent Inbox。
7. **授权**。申请、审批、用量、到期时间线与快捷键。
8. **连接器**。健康卡片、检查历史、延迟与错误原因。
9. **策略**。JSON 校验、diff、示例 principal 试算、版本历史、保存确认。
10. **审计**。按租户、动作、状态、trace 过滤；链状态、Verify 按钮、导出。
11. **设计系统**。shadcn/ui、assistant-ui、Recharts、React Flow；暗色模式、密度切换、中英 i18n、WCAG AA、空状态、骨架屏与 toast。
12. **技术选型**。前端独立成 React + TypeScript + Vite + TanStack Router/Query，控制台服务保留 API。Trace 与 Eval 优先接 Langfuse 或 Phoenix，镜像仓库直接用 Harbor，不要自研完整可观测平台。

## 五、候选切片

- [SLICE-110 OTel 导出](../specs/SLICE-110-otel-tracing.md)
- [SLICE-111 运行检查点](../specs/SLICE-111-durable-run-checkpoints.md)
- [SLICE-112 护栏管线](../specs/SLICE-112-guardrails-pipeline.md)

## 六、不建议

- 不做全功能可视化编排，除非有非技术用户。ADK 是 code-first，画布收益有限。
- 不用 OTel 替换审计链。审计是合规证据，trace 是调试工具。
- 不一次性引入所有开源组件，每引入一个都要评估运维与许可。
- 不只按星数选型。Langfuse、Dify、Open WebUI、LiteLLM、Flowise 的许可不是标准 SPDX 标注，直接嵌入或改品牌前先核对条款。

## 七、数据与许可

- 星数与仓库描述取自 GitHub API，日期 2026-11-15。
- 星数会变化，只用于判断项目成熟度与社区规模。
- 直接嵌入代码或 UI 前核对 LICENSE。MIT 与 Apache-2.0 的项目更适合复用；标注 NOASSERTION 的项目需要逐条确认。
