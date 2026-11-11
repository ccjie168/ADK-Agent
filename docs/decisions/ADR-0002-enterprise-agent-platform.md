# ADR-0002 企业级 agent 平台架构

状态: Accepted   日期: 2026-11-11   批准: Jie CAO（会话确认）

## 背景

目标是用 ADK 做一个企业内部的 agent 开发框架，覆盖 agent 的开发、注册、安全和使用。Agent 通过函数、API、MCP 访问应用和数据。应用既是 agent 的消费者，也是 agent 的提供方。模型通道走 LiteLLM 或 vLLM。

现有仓库 `adk-agent` 是数据面的种子。它已经能构造 agent、消费 MCP、暴露 MCP、加 bearer 鉴权、跑私有控制台，有 31 个测试和唯一门禁 `scripts/check.py`。缺的是控制面、治理面和编排。

## 决定

### 1. 分成三个平面

- **控制面**：开发、模板、注册、版本、发布、下线。
- **数据面**：运行、编排、会话、工具调用、模型调用。
- **治理面**：身份、鉴权、策略、密钥、审计、配额。

三个平面可以在一个进程中运行，但代码边界和权限边界先立好。拆分时按平面拆，不按功能列表拆。

### 2. 模块化单体加端口

第一阶段是一个可部署单元，内部按平面分模块。所有外部能力走 `typing.Protocol` 端口，默认适配器进程内实现。插件通过 `importlib.metadata.entry_points` 注册。

端口清单：

`AgentRegistry`、`ModelGateway`、`ToolGateway`、`SessionStore`、`PolicyEngine`、`SecretProvider`、`AuditSink`、`IdentityProvider`、`OrchestratorStrategy`、`TemplateSource`。

依赖规则：`core/` 只定义领域类型和端口，不导入任何适配器。适配器只向内依赖。所有装配在 composition root。用 import-linter 写进 `scripts/check.py`，反向导入直接让门禁失败。

否决第一天微服务。没有规模证据，分布式故障、服务发现、跨服务鉴权会先吃掉迭代速度。微服务拆分判据见第 9 条。

### 3. 契约先于代码

以下五个类型进 `docs/contracts/`，并成为 `core/` 的领域类型。改契约先改文档，再改代码。

- `AgentManifest`：id、version、owner、description、model_policy、tool_grants、data_scopes、exposure、eval_suite、slo。
- `PublishedAgent`：manifest、digest、signature、published_at。digest 是 manifest 规范 JSON 的哈希，不写入 manifest 自身。
- `AgentRef`：`id@version` 加 digest。生产只认 digest，不认 latest。
- `Principal`：tenant、subject、kind、roles、attributes。每个 run 都有 principal。
- `Invocation`：run_id、trace_id、principal、agent_ref、输入、deadline、预算。
- `AuditEvent`：run_id、trace_id、tenant、principal、agent_ref、manifest_digest、action、target、args_hash、result_hash、policy_decision_id、data_classes、latency、tokens、cost、egress、status、error_code。

manifest 版本不可变，发布时签名。运行时按 digest 拉取。

### 4. 编排计划是数据

编排分两层。Agent 内部用 ADK 的 `sub_agents` 和顺序、并行 agent。平台层用一个确定性的 `PlanExecutor`，策略包括单 agent、路由、监督者、工作流 DAG、扇出扇入、人工审批。

执行器持有 run 状态，负责重试、超时、预算、取消、trace 和审计。它通过 `invoke(agent_ref, input)` 调 agent。编排逻辑不写进 prompt，因为 prompt 决策不可复现、不可审计、不可配额。

持久化先做数据库队列加接口。需要跨天长等待工作流时再接 Temporal。

### 5. 三个强制执行点

策略决策与策略执行分开。执行只发生在这三处：

- 模型网关：所有模型出口。
- 工具网关：所有外部数据访问。
- agent 调用入口：谁能调谁。

绕过网关的调用在架构上不可达。数据分级标签打在工具和数据源上。策略匹配 principal、tenant、agent、数据类、动作。

### 6. 审计是追加事件流

审计不是普通日志。一次状态变更一条事件，串在同一个 `trace_id` 下，覆盖 orchestrator、agent、tool、model 四层。按 tenant 和日期做哈希链，提供篡改检测。输入输出是否落盘由数据策略决定，默认脱敏。保留期和 PII 规则属于策略，不是运维补丁。

工具在受限 worker 中执行，有 CPU、内存、时间、网络限制。不可信 MCP 服务器网络隔离。

### 7. 身份：OIDC 是默认适配器，不是第一天硬依赖

硬要求只有五条：

1. 每个请求都有唯一、可验证的主体。
2. 凭据不共享。
3. agent 身份独立于用户身份。
4. 每条审计事件带主体。
5. 存在撤销路径。

实现方式可以是 OIDC、云 workload identity、mTLS、SPIFFE、client credentials，早期也可以是内网 API key 加本地管理员。

默认适配器用 OIDC，由 ingress 终结认证，应用只接收已验证的主体。信任 ingress 转发的主体的前提是只有 ingress 能访问应用。网络隔离不成立时不得信任请求头。

`IdentityProvider` 端口从第一天就在，`Principal` 和 `tenant` 从第一天就在数据模型里。单团队 MVP 可以不接 OIDC。多团队、SSO 与离职流程、合规要求、跨系统单点登录出现时，OIDC 变为必须。

### 8. 部署：Compose 加 Postgres 起步

Phase 0 到 2 用 Docker Compose 加 Postgres，单机内网。

- 不用 SQLite 作为平台存储。注册表、审计流、会话需要并发和持久写入。SQLite 只用于单 agent 演示。
- 例外：企业已有 paved-road K8s 集群，ingress、密钥、监控现成，可以直接上 K8s。不为本项目自建集群。

迁移前必须已经做到：

1. 状态外部化到 Postgres、对象存储、队列，本地盘不存状态。
2. 配置全走环境变量。
3. 保留 `/healthz` 和优雅停机。
4. 应用代码不调用 K8s API。

做到这四条，Compose 到 K8s 是部署变更，不是代码变更。

迁 K8s 的触发条件：多团队独立发布、运行时 worker 横向扩容、严格网络策略和租户隔离、高可用、沙箱 worker 隔离。

### 9. 微服务拆分判据

先一个可部署单元，保留五个逻辑接缝：控制面 API、运行时 worker、模型网关、工具网关、审计管线。

只有三个判据能触发拆分：独立扩缩容、独立信任边界、独立故障域。模型网关和工具网关最先拆，因为它们是安全边界。运行时 worker 其次。控制面和审计最后。

不按“每个 agent 一个服务”拆。agent 是数据，不是服务。

### 10. 路线图

- Phase 0，地基：修评审 P0，写本 ADR 与五个契约，搭端口骨架，导入 import-linter。
- Phase 1，单 agent 垂直切片：注册表、manifest 校验与发布、模型网关、principal 与 trace 注入、基础模板。
- Phase 2，工具网关与策略：函数、OpenAPI、MCP 代理，策略引擎，密钥，工具沙箱。
- Phase 3，编排器：plan schema、策略、持久化执行、人工审批、trace 树。
- Phase 4，平台加固：多租户、配额、RBAC、评测门禁、灰度、A2A 评估。
- Phase 5，按接缝拆分服务。

每个阶段是一个或多个切片，先写会红的反例测试，再实现。现有 SLICE-001 到 007 已覆盖数据面的一部分，Phase 0 直接接上，不推翻。

## 后果

- 改变对外接口前，先改 `docs/contracts/`。
- 新增模型通道或第三方流程包，仍按 ADR-0001 要求先登记。
- 所有 agent 调用经过编排器，所有模型和工具调用经过网关。没有第二条路径。
- 审计事件、manifest 和签名的存储结构一旦定下，变更需要新 ADR。
- Compose 是当前部署方式，K8s 清单保留但不作为近期目标。
- 分层规则由 import-linter 在门禁中强制，不靠文档约定。
