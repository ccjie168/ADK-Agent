# 架构与方向评审：七条要求对现状

日期: 2026-11-13
范围: 对照 ADR-0001 到 ADR-0007、`docs/contracts/`、`src/adk_agent` 现状，评估七条产品要求，给出演进路线。
状态: 结论待确认。本文不是 ADR；确认后，架构缺口按 ADR 流程立项。

## 结论摘要

| # | 要求 | 判断 | 主要缺口 |
| --- | --- | --- | --- |
| 1 | 企业级平台和框架 | 结构到位，运营面未闭环 | 控制面仍是 CLI 加文件目录；平台状态在本地盘；单写者 |
| 2 | 开发、注册、维护、运行，分布式运行加集中治理 | 部分满足 | 发布只登记元数据，不承载可运行工件；审计服务只写不读；控制台的 runs/audit 是本进程缓冲 |
| 3 | 模板简化开发，标准 agent 组成市场 | 起步 | 只有一个内置模板；无工件、无发布者签名、无发现/安装接口、无市场界面 |
| 4 | 工具库：API、MCP、函数、connector，带授权与治理 | 部分满足 | 无工具目录；无 connector 生命周期；无工具级配额；无治理界面 |
| 5 | 同时作为 agent 提供方和消费方 | 部分满足 | A2A 双向可用，但只有单一共享 token；`exposure` 只是声明；peer 授权缺失 |
| 6 | 可插拔、模块化 | 基本满足 | 端口和分层已强制；entry_points 插件发现未实现；外部模板源未实现 |
| 7 | 模型接入：LiteLLM API 与本地 vLLM | 满足 | 网关、熔断、审计、指标齐全；租户级成本预算未进运行路径 |

七条要求与 ADR-0002 同向，没有需要推翻的方向。真正的缺口不是"再加功能"，而是两件事：

1. **注册的东西不能直接跑。** 注册表存的是 manifest 和评测报告；运行时仍从本地 `agent.py` 加载 agent。市场、版本固定、按 digest 运行这三件事都卡在这里。
2. **治理面只有写路径，没有读路径。** 审计、运行历史、注册表都在本地文件或进程内存里。多副本运行了，但"集中可见性"还没有落地。

## 逐条评估

### 1. 企业级 AI agent 平台和框架

**已具备**

- ADR-0002 规定的三平面、端口和依赖规则已落地，`core/` 不导入适配器由 import-linter 在门禁里强制（`scripts/check.py`）。
- 治理面：OIDC（ADR-0007）、租户与 RLS（SLICE-052）、配额（SLICE-044）、审计哈希链与签名轮换（SLICE-035、053、060）、入口限流（SLICE-058、059）、备份（SLICE-055）。
- 数据面：编排执行器、审批、MCP/A2A 运行、SSE 进度（SLICE-023 到 036）。

**缺口**

- 控制面没有服务化。发布是 `adk-agent publish` 直接写目录，没有控制面 API、没有生命周期状态（active/deprecated/retired）、没有发布审计事件。
- ADR-0002 第 8 条要求"本地盘不存状态"，但注册表、审批收件箱、审计 JSONL、备份仍是本地文件。单机试点可以接受，横向扩容时面对的是共享卷或必须换后端。
- 平台自身的管理员 API（租户开通、角色管理、密钥配置）不存在；租户来自 token，角色来自 token 或启动参数。

### 2. 开发、注册、维护、运行，分布式运行加集中可见性

**已具备**

- 注册：`<registry>/<tenant>/<id>/<version>.json`，版本不可变，digest 固定，评测门禁（SLICE-012、030）。
- 运行：控制台、MCP（stdio 与 streamable-http）、A2A 三种面；共享会话（ADR-0005）、共享配额、审计服务、指标（SLICE-047、050）。
- 维护：灰度选择器（`canary.py`）、评测报告留存、审批归档。

**缺口**

- **工件缺失**：`PublishedAgent` 只有 manifest、digest、signature、时间。没有代码包、依赖声明、运行镜像或入口。控制台和 MCP 仍用 `--agents`/`--agent` 指向本地 Python 文件。按 `AgentRef@digest` 运行在生产路径上还不存在。
- **集中可见性缺失**：审计服务只有 `POST /v1/events`，没有查询接口；控制台 `GET /api/audit`、`GET /api/runs` 读的是进程内 `ListAuditSink`（`console.py` 的 `_visible_events(audit.recent(1000), ...)`），控制台也没有 `--audit-url`。换一个副本，面板就是空的。
- 注册表的读路径是文件系统。跨节点部署要么共享卷，要么把注册表做成服务。
- 注册表变更没有审计事件，`publish` 不可追溯。

### 3. 模板与 agent 市场

**已具备**

- `adk-agent new` 加内置 `minimal` 模板；模板生成物通过 `AgentManifest` 校验。
- 注册表可以列出租户下的 agent 与评测报告，控制台有只读运营视图（SLICE-038）。

**缺口**

- 模板只有内置一个，没有版本、分类、说明和示例的目录结构；ADR-0002 里的 `TemplateSource` 端口没有外部实现。
- 市场需要的三件事都缺：**发现**（搜索、分类、详情 API 与界面）、**信任**（发布者密钥与签名；当前 `PublishedAgent.signature` 是 digest 的 sha256 标记，不是密码学签名）、**安装/运行**（工件包与按 digest 加载）。
- 没有兼容性元数据（ADK 版本、Python 版本、依赖）。

### 4. 工具库

**已具备**

- 三种工具形态：函数（`FunctionToolGateway`）、OpenAPI（`tools/sources.py`）、MCP（代理与客户端）。
- 治理：`GrantPolicyEngine` 授权、工具守卫、数据分级标签、沙箱、审计、密钥提供者（`secretstore`）。

**缺口**

- 没有工具目录。工具在 agent 代码或工具文件里定义，无法登记、检索、复用，也没有"这个工具被哪些 agent 使用"的视图。
- Connector 生命周期缺失：OAuth 授权跳转、token 刷新、凭据轮换、吊销都没有；`SecretProvider` 只解决"取一个密钥"。
- 工具级配额和限流缺失。现有配额按租户 run，限流按调用方请求；单个昂贵工具没有独立预算。
- 没有工具治理 API 或界面（没有 `/api/tools`）。

### 5. 双向 agent 服务

**已具备**

- 提供方：`serve-a2a` 暴露 agent card 与 JSON-RPC，带 bearer、审计、配额、限流（SLICE-031、048、059）。
- 消费方：`remote_agent` 构造 `RemoteA2aAgent`，可当本地 agent 使用。

**缺口**

- ADR-0003 记录的限制还在：单一共享 token，没有 per-peer 身份、没有"哪个 peer 能调哪个 agent"的授权映射，没有速率与配额的 peer 维度。
- `exposure` 字段只是声明，注册表和运行时都不消费它；把 agent 注册为 `exposure="a2a"` 不会自动暴露。
- 远端 agent 作为消费方时，它的模型与工具调用发生在对端，本平台只审计 `agent.run` 外层，看不到对端内部；跨组织的治理边界没有文档化。

### 6. 可插拔与模块化

**已具备**

- `core/` 端口齐全，适配器在 composition root 装配；重依赖用 optional extra（`litellm`、`oidc`、`a2a` 由 ADR-0003 保持可选）。
- import-linter 把"core 不导入适配器"写进门禁。

**缺口**

- ADR-0002 第 2 条的 `importlib.metadata.entry_points` 插件发现没有实现。现在换注册表、审计、模型网关等适配器要改代码，不能靠安装包注册。
- 模板源、工具源没有统一的插件契约和示例包。
- 缺少"第三方如何扩展平台"的文档与一个最小插件样例。

### 7. 模型接入

**已具备**

- LiteLLM 与 vLLM 两种 provider（`models/providers.py`），独立模型网关（ADR-0004），provider 熔断（SLICE-054），调用审计与指标，`HttpModelGateway` 跨进程客户端。

**缺口**

- 成本预算只在计划执行器里检查（`orchestration/executor.py` 的 `_check_budget`）。控制台聊天和 MCP/A2A 单 agent 路径没有预算上限，只有租户 run 配额。
- 没有按租户的模型目录与价格表，成本审计靠 provider 返回的 `cost_usd`。
- 新增模型通道要新 ADR，这一点仍然正确，保持不变。

## 与 ADR 的一致性检查

| ADR 条款 | 现状 | 结论 |
| --- | --- | --- |
| 0002 §2 插件经 entry_points 注册 | 未实现，装配写死在 composition root | 与 ADR 不符，补实现或修 ADR |
| 0002 §3 PublishedAgent 发布时签名 | `signature` 是 digest 的 sha256 标记，非密钥签名 | 与 ADR 不符，需要工件与签名 ADR |
| 0002 §8 本地盘不存状态 | 注册表、审批、审计、备份都在本地文件 | 单机试点可接受，迁 K8s 前必须解决 |
| 0002 §9 按接缝拆服务 | 模型、工具、审计已拆；控制面未建 | 符合，控制面是下一个接缝 |
| 0003 A2A per-peer 身份后续补 | 仍未补，已有共享 token 和限流 | 保持记录，排入服务面路线 |
| 0004/0005/0006 网关、会话、审计 | 已实现并有证据 | 一致 |
| 0007 OIDC | 五个 HTTP 面已接线 | 一致，未接 introspection 与撤销 |

## 演进路线

优先级按"解锁最多后续工作"排序，不按功能多少排序。

### Phase A 集中可见性（建议先做，1 到 2 刀）

- **A1 审计只读 API**：`GET /v1/events`（按 tenant、trace、run、时间过滤，admin 可跨租户），返回 `AuditRecord` 或摘要；契约先行。
- **A2 控制台接共享审计**：`console --audit-url` 同时作为写路径和读路径；`/api/audit` 与 `/api/runs` 从服务读；本进程缓冲退化为离线兜底。
- 为什么先做：这是"集中可见性"的最小闭环，改动小，立刻让多副本部署的面板有意义；也为后面的注册表服务提供读模型范式。

### Phase B 工件与市场（3 到 5 刀，先 ADR）

- **B1 ADR-0008 工件与发布者签名**：agent 工件形态（代码包 + 依赖声明 + manifest + 入口）、digest 寻址、发布者密钥与验签、运行时按 `AgentRef@digest` 加载、加载沙箱。
- **B2 注册表服务化**：HTTP 控制面 API、生命周期状态、变更审计、Postgres 或对象存储后端；文件注册表保留为单机实现。
- **B3 模板目录**：`TemplateSource` 经 entry_points 发现，模板带版本与元数据，`new --template <len>`。
- **B4 市场视图**：搜索、详情、评测报告、一键生成项目；控制台新增 Marketplace 面板。
- 市场是要求 3 的核心，也是最大的架构决策，必须先有 ADR 再动代码。

### Phase C 工具库与连接器（3 到 4 刀）

- **C1 工具目录**：登记 tool/toolset 元数据与数据分级，grant 引用目录条目，控制台工具页。
- **C2 Connector 生命周期**：OAuth2 授权码与 client credentials、token 刷新、轮换与吊销，接入 `SecretProvider`。
- **C3 工具级配额与限流**：在工具网关按 tool_id 限速与计费，补审计维度。

### Phase D 双向服务面（2 到 3 刀）

- **D1 peer 身份**：per-peer principal、调用授权映射（peer → agent → 动作），agent card 按 `exposure` 强制。
- **D2 远端 agent 入目录**：把 A2A peer 作为一等目录条目，带信任标记与策略；文档化跨组织审计边界。

### Phase E 平台运行（持续）

- Postgres 注册表与审计后端、跨副本共享限流（需 ADR，Redis 或入口网关）。
- 压测长稳补齐控制面；Postgres 备份用 `pg_dump` 纳入运维手册。
- K8s 清单升级为多副本，前提是 Phase A 与 B2 完成。

### 不建议现在做

- 按"每个 agent 一个服务"拆分。ADR-0002 §9 已否决，仍然正确。
- 自建模型路由或评测平台。现有 provider 网关和 eval 门禁够用。
- 多 issuer、撤销列表、KMS。等真实合规需求。

## 已确认的决策

2026-11-13 确认，四条都选"先收紧、留插拔"：

1. **工件形态：灵活插拔。** 不把工件格式写死成一种。抽象成 `ArtifactStore` 加 `ArtifactLoader` 端口，第一版用进程内 Python 包加载器，后续可以加容器或镜像加载器，注册表与运行时都不感知具体形态。ADR-0008 按这个方向写。
2. **注册表后端：先 Postgres。** 元数据和 manifest 进 Postgres，保留 `AgentRegistry` 端口；文件注册表降级为单机演示实现。对象存储等规模上来后再演进。
3. **市场范围：先对内。** 目录按租户隔离，只做同租户发现与安装；跨租户公开和第三方签名信任模型后续再议。
4. **A2A 联邦：先内部 peer。** 近期只支持组织内 peer，用内部身份签发；agent card 不对公网开放。per-peer 授权映射仍按 Phase D 做。

这些选择把 Phase B 缩小为"内部工件仓库加内部目录"，不引入公网市场和跨组织信任。Phase A 可以直接开工。
