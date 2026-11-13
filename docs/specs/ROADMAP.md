# ROADMAP 企业级 agent 平台

状态: active   依据: ADR-0002   日期: 2026-11-11

当前进度与交接说明见 `docs/PROGRESS.md`。

## 规则

- 里程碑是门，不是日期。日期可以作为目标，不作为通过条件。
- 每个切片引用它实现的 ADR-0002 条款号。
- 切片不能和 ADR 冲突。实现中发现方向要改，先改 ADR 或出新 ADR，再改代码。
- 每个切片先写会红的反例测试，再实现。
- 每个切片完成跑 `python scripts/check.py --fast`，然后合并。
- 每个里程碑出口跑 `python scripts/check.py --full`，结果写进 `docs/evidence/`。
- 后续里程碑的切片在进入该里程碑时细化。现在只细化 M0。

## 文档链

```
ADR-0002 -> docs/contracts/ -> docs/specs/SLICE-xxx.md -> code -> docs/evidence/ -> scripts/check.py
```

为什么看 ADR，接口看契约，这一刀看 spec，证据看 evidence，强制看门禁。

## 里程碑

| 里程碑 | 阶段 | 出口标准 | 状态 |
| --- | --- | --- | --- |
| M0 地基 | Phase 0 | 五个契约合并，import-linter 生效，manifest 可往返，P0 加固完成 | done |
| M1 单 agent 闭环 | Phase 1 | 注册、发布、模型网关、审计端到端跑通 | done |
| M2 工具与策略 | Phase 2 | 越权工具调用被拒并留痕，沙箱生效 | done |
| M3 编排 | Phase 3 | 多 agent 工作流可回放，审批门生效 | done |
| M4 平台加固 | Phase 4 | 两租户隔离，配额生效，评测不过不能发布 | done |
| M5 拆分 | Phase 5 | 网关与 worker 独立部署，故障隔离 | done |

## M0 切片

| 切片 | 内容 | 依据 | 依赖 |
| --- | --- | --- | --- |
| SLICE-008 | 核心契约与领域类型 | ADR-0002 第 2、3 条 | 无 |
| SLICE-009 | 包骨架、端口与分层门禁 | ADR-0002 第 2 条 | 008 |
| SLICE-010 | 评审 P0 加固 | ADR-0002 第 5、6 条 | 无 |
| SLICE-011 | 模型与配置契约收敛 | ADR-0002 第 2、3、8 条 | 008, 009 |

M0 出口证据见 `docs/evidence/M0-milestone.txt`。

M0 出口标准：

1. `docs/contracts/` 的五个 schema 合并，模型与 schema 一致。
2. `core/` 只定义类型和端口，import-linter 在 `check.py` 中强制。
3. `AgentManifest` 可 JSON 往返，未知字段被拒绝，digest 稳定。
4. 评审 P0 加固完成，`--fast` 全绿。
5. `check.py --full` 结果写入 `docs/evidence/`。

## M1 切片

- SLICE-012 注册表与发布：文件注册表、不可变版本、digest 钉住、`validate` / `publish` CLI、id/version 路径安全。
- SLICE-013 模型网关：provider 白名单、token 与成本审计、vLLM 适配器。
- SLICE-014 运行时注入：principal、run_id、trace_id 贯通。
- SLICE-015 基础模板：模板生成器与校验。
- SLICE-016 审计闭环与控制台 v0：内存审计、`/api/audit`、页面审计面板。
- SLICE-017 模型网关接入：把网关接到 ADK 模型循环，agent run 产生 `model.call` 事件。
- SLICE-018 安全门强制 Phase A：pre-commit hook、CI 必需检查、bandit 覆盖 scripts、spec 威胁模型门禁。

M1 出口证据见 `docs/evidence/M1-milestone.txt`。MCP `serve_agent` 路径的网关接入移到 M2。

SLICE-018 Phase B 需要新 ADR 或工具决策，排在 M2：依赖锁、历史密钥扫描、镜像扫描、SBOM 校验、日志脱敏。

进入每个切片时再写详细 spec。

## M2 切片

- SLICE-019 工具网关与策略：函数注册、GrantPolicyEngine、tool.call 审计。
- SLICE-020 ADK 工具守卫接入：before/after tool callback，agent 工具调用经过网关。
- SLICE-021 密钥提供者与工具源：SecretProvider、OpenAPI 导入、MCP 代理。
- SLICE-022 工具沙箱：资源与网络限制。

SLICE-019、SLICE-020、SLICE-021、SLICE-022 已完成。M2 收口。

M2 出口证据见 `docs/evidence/M2-milestone.txt`。

进入每个切片时再写详细 spec。

## M3 切片

- SLICE-023 编排计划与执行器：OrchestrationPlan、单 agent、顺序、agent.invoke 策略、审计。已完成。
- SLICE-024 执行韧性：重试、超时、预算、取消。已完成。
- SLICE-025 路由与扇出扇入：RouteWhen、唯一汇合点、max_parallel。已完成。
- SLICE-026 监督者：监督 agent 选择 worker，轮次上限，结构化决策。已完成。
- SLICE-027 人工审批与 trace 树。已完成。

M3 收口。

M3 出口证据见 `docs/evidence/M3-milestone.txt`。

进入每个切片时再写详细 spec。

## M4 切片

- SLICE-028 租户隔离与配额：manifest 带租户、注册表按租户分目录、查询带租户、每租户运行与并发配额。已完成。
- SLICE-029 RBAC 与策略管理界面：租户角色绑定、拒绝优先、控制台策略接口与面板、聊天策略检查。已完成。
- SLICE-030 评测门禁与灰度：确定性评测套件与报告、发布门禁、`eval` 命令、按权重选版本的灰度路由器。已完成。
- SLICE-031 A2A 消费方与提供方评估：ADR-0003，可选提供方与消费方适配器，全路径 bearer 鉴权。已完成。

M4 收口。

M4 出口证据见 `docs/evidence/M4-milestone.txt`。

进入每个切片时再写详细 spec。

## UI 切片

- SLICE-036 控制台运行进度与 trace 视图：SSE 进度事件、时间线、trace 面板。已完成。

## M5 切片

- SLICE-032 模型网关独立部署：跨进程契约、HTTP 服务、鉴权、JSONL 审计、`HttpModelGateway` 客户端。已完成。
- SLICE-033 工具网关独立部署：grants 契约、HTTP 服务、鉴权、客户端、工具文件加载。已完成。
- SLICE-034 运行时 worker 横向扩容：`SESSION_URL` 共享 Postgres 会话、缺驱动显式失败、控制台与 MCP 共用存储。已完成。
- SLICE-035 审计管线独立部署：`AuditRecord` 租户哈希链、审计服务、`HttpAuditSink`、`verify-audit`。已完成。

M5 收口。

M5 出口证据见 `docs/evidence/M5-milestone.txt`。

进入每个切片时再写详细 spec。

## 生产化切片

- SLICE-037 审计客户端接入网关：两个网关用 `--audit-url` 把事件发给独立审计服务，审计 token 只从环境变量读，非回环地址强制鉴权。已完成。
- SLICE-038 只读运营视图（UI-1）：注册表、run 历史和会话的只读接口与面板，发布时留存评测报告。已完成。
- SLICE-039 OIDC 身份解析器核心：验证 JWT 并映射成 `Principal`，只做解析器，不接 HTTP。已完成。
- SLICE-040 OIDC 接线，控制台与中间件：`OidcAuthMiddleware`、`console --oidc-config`、按 subject 的会话和读视图的租户隔离。已完成。
- SLICE-041 OIDC 接线，服务面：模型网关、工具网关和审计服务。已完成。
- SLICE-042 MCP HTTP OIDC 认证：`serve` 和 `serve-many` 的 streamable-http 鉴权。已完成。
- SLICE-043 MCP principal 注入：把 token 主体带进 ADK 的 MCP 运行和会话归属。已完成。
- SLICE-044 共享配额：`QuotaConfig`、Postgres 配额后端，控制台按租户限流。已完成。
- SLICE-045 审批收件箱与计划可视化（UI-2）：目录收件箱、审批接口、Approvals 和 Plans 面板。已完成。
- SLICE-046 MCP 运行路径审计与配额：包装 `_run_agent` 的 runner，补 `agent.run` 审计和租户配额。已完成。
- SLICE-047 指标与 trace 传播：`MetricsRegistry`、控制台 `/metrics`、`traceparent` 入站和 `X-Trace-Id` 出站。已完成。
- SLICE-048 A2A 运行路径审计与配额：通用 `AuditedRunner`、A2A 审计、配额和 traceparent。已完成。
- SLICE-049 审批过期与提交提醒：`expires_at`、收件箱过期语义、`on_submit` 回调和控制台 410。已完成。
- SLICE-050 服务指标端点：模型网关、工具网关和 MCP 的 `/metrics`，运行和调用计数。已完成。跨副本聚合交给抓取端。
- SLICE-051 审批记录归档与删除：`prune` 和 `approvals prune` 子命令。已完成。
- SLICE-052 配额表行级隔离：Postgres RLS、事务级租户设置。已完成。
- SLICE-053 审计轮转与签名：按记录数分段的哈希链、逐记录 HMAC 和跨段校验。已完成。
- SLICE-054 模型调用熔断：三态熔断器、provider 包装和网关 503。已完成。
- SLICE-055 文件状态备份与恢复：`backup`/`restore` 子命令、manifest 和安全解包。已完成。
- SLICE-056 压测基线：`scripts/loadtest.py` 的配额并发与审计吞吐测量，并记录实机基线。已完成。
- SLICE-057 SSE 慢客户端与有界进度队列：`ProgressBuffer`、`--sse-queue-size`、`sse` 压测场景。已完成。
- SLICE-058 入口限流：固定窗口限流器、四个服务的 `--rate-limit`、429 与拒绝计数。已完成。
- SLICE-059 MCP 与 A2A 入口限流：同一中间件接到 `serve` / `serve-many` / `serve-a2a`。已完成。
- SLICE-060 审计签名密钥轮换：记录加 `kid`、密钥环、按 `kid` 验签。已完成。
- SLICE-061 会话按租户隔离：可选的 `<tenant>:<subject>` 会话键。已完成。
- SLICE-062 审计只读查询：`GET /v1/events` 与 `query_events`，集中可见性的第一步。已完成。
- SLICE-063 控制台接共享审计：`--audit-url`/`--audit-file` 读写同一份审计数据。已完成。
- SLICE-064 工件类型与端口：`AgentArtifact`、`ArtifactStore`/`ArtifactLoader`、契约。已完成。
- SLICE-065 工件存储：文件内容寻址与 Postgres `adk_artifacts` 两个实现。已完成。
- SLICE-066 发布带工件与签名：确定性 zip、Ed25519、`publish --artifact`。已完成。
- SLICE-067 工件加载与验签：可信密钥表、进程内加载器、`load_agent`。已完成。
- SLICE-068 从注册表启动：控制台与 MCP 的 `--agent-ref` 加载路径。已完成。
- SLICE-069 市场视图与工件状态（UI-3）：注册表页展示工件摘要与验签徽标。已完成。
- SLICE-070 Postgres 注册表：`adk_agent_versions`、不可变版本与幂等发布、共享惰性连接池。已完成。
- SLICE-071 注册表控制面与客户端：`serve-registry` 五个端点、租户绑定、两步发布、`HttpAgentRegistry`。已完成。
- SLICE-072 命令接注册表服务：`console`/`serve`/`serve-many`/`publish` 的 `--registry-url`，发布两步上传。已完成。
- SLICE-073 市场页按需加载：`POST /api/registry/load`、验签后注册运行时、`--max-loaded-agents`。已完成。
- SLICE-074 评测报告集中存储：`adk_eval_reports`、服务 GET/PUT 报告、`HttpEvalReportStore`、发布带报告。已完成。
- SLICE-075 只读工具目录（UI-4）：`ToolCatalog`、`--tool-catalog`、`/api/tools` 叠加注册表授权、Tools 面板。已完成。
- SLICE-076 生命周期存储与接口（ADR-0010）：`AgentLifecycle` 转换、文件/Postgres 存储、控制面 GET/PUT、审计。已完成。
- SLICE-077 生命周期拦截与控制台：按引用与按需加载拒绝退役版本、市场页徽标、`lifecycle set` 命令。已完成。
- SLICE-078 工具授权请求存储（ADR-0011）：`ToolGrantRequest` 状态与到期、文件/Postgres 存储、有效授权查询。已完成。
- SLICE-079 MCP 与 A2A 工具授权：`install_declared_guards`、manifest 授权优先、运行时 invocation 上下文与 `require_context`。已完成。
- SLICE-080 运行时合并临时授权：`GrantPolicyEngine` overlay、`grant_store_unavailable`、三个命令的授权存储配置。已完成。
- SLICE-081 工具授权申请与审批：控制台三个接口、Grants 面板、`tool-grants` 命令，ADR-0011 闭环。已完成。
- SLICE-082 工具授权使用统计：`AuditEvent.policy_version`、用量聚合接口、到期徽标。已完成。
- SLICE-083 市场页卸载与置换：`POST /api/registry/unload`、按需加载租户记录、Unload 按钮与 name_conflict 自动置换。已完成。

## 完成定义

一个切片完成，需要同时满足：

- spec 状态为 gated 或 merged。
- 反例测试先红，实现后绿。
- `check.py --fast` 全绿。
- 涉及对外接口时，契约已先合并。

一个里程碑完成，需要同时满足：

- 该里程碑所有切片合并。
- 出口标准逐条有证据。
- `check.py --full` 全绿，输出写入 `docs/evidence/`。
