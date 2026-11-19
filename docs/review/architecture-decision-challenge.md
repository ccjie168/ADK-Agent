# Architecture Decision Challenge

状态：评审产物，供 Owner 确认。不修改 `decision-register-draft.md` 与 `fr-acceptance-matrix-draft.md`，本轮只挑战与重写，等确认后再决定是否替换原文件。
输入：两份草稿、目标规格 `docs/specs/ADK_Agent_Product_Architecture_Specification_v1.0.docx`、已核实的 AS-IS 实现。
目标：不是找更多缺口，而是挑战现有缺口、MVP 范围、优先级和默认值是否真的成立。

---

## 1. Findings I Agree With

这些判断经过挑战后仍成立，我继续坚持：

1. **风险分级是布尔值表达不了分级**。`core/policy.py:17` 只有 `requires_approval: bool`，而目标需要 L1–L4。这不是架构洁癖，它直接决定工具授权 → 风险分级 → 审批要求 → 执行策略 → 审计。
2. **角色模型优先级应高于 Planner**。`cli.py:1436` 的 `--role` 默认 `admin`，是比「要不要 Planner」更严重的问题。
3. **RAG 先定义端口，不先选厂商**。`RagService` 端口 + ACL 契约先于向量库选型，符合「架构 ≠ 选型」。
4. **GREY 用于 NFR 是对的**。仓库有 `scripts/loadtest.py` 不等于支持 1000 并发；这类能力必须用压测/演练证据证明，不能凭仓库猜生产能力。
5. **FR-010 模型路由是 RED**。现在没有 alias、路由、降级、预算执行；且代码结构必须收敛到 Model Policy → Model Alias → Gateway → Endpoint，不能让 `if provider == ...` 散落。
6. **网关策略信任边界是我上一轮评审的 P0**（F-01/F-02）。模型网关和工具网关从请求体读取 `policy`/`grants`，这是「谁能用什么模型、调用什么工具」的信任基础，必须先修。

---

## 2. Findings I Challenge

我挑战我自己草稿里的三处「看似合理、实际滑向了必须这样实现」：

1. **FR-003/004/005 被写成了强制 Agent 角色**。我把目标文档 8.1 的 Planner/Specialist/Reviewer 直接当成 Must 的 FR。这是错误的。目标文档 8.1 是一种 Reference Pattern，不是产品需求。强制实现三个 Agent 属于为了把 RED 变 GREEN 而过度设计。

2. **D-01 的 MVP 默认是 Platform MVP**。我建议的 MVP 清单（FR-001/004/006/007/010/011/013/014）没有 RAG、没有真实业务场景，验证出来的只会是「平台能跑」，不是「企业 Agent 有业务价值」。这是我的偏平台视角造成的。

3. **D-05 被拍成单一授权模式**。我把「服务账号 + ACL 元数据过滤」当 Recommended Default。这不成立：RAG/SharePoint 适合服务身份 + ACL 执行，但 SAP 写操作只靠服务账号会丢失最小权限和非抵赖，必须按集成类型区分。

4. **数字参数被写成 Recommended Default**。4 小时审批 SLA、30 分钟 ACL 同步、13 个月保留、100 并发、10%/30 分钟 canary——这些是「AI 提出的参数起点」，不是「已批准的要求」。我错误地把它们写成默认值。

---

## 3. FRs That Should Be Rewritten

原则：把「Agent 角色」改成「能力需求」，实现是设计决定。对每个 RED 项回答：是否真需要、MVP 是否需要、现状是否真不足、目标是否过度规定、能否用更简单实现满足、保持 RED 的业务/生产风险。

### FR-003 Planner Agent → Structured Task Planning

- 真需要吗：部分。两个 MVP 场景可被确定性工作流分解，不需要 Planner Agent。
- MVP 需要吗：需要的是「结构化分解 + 成功条件 + 风险分级」，不是 Planner Agent。
- 现状不足吗：`PlanExecutor` 已有 deterministic 计划 + supervisor 策略，结构已存在，缺的是 schema 化的成功条件与风险分级。
- 目标是否过度规定：是。强制 Planner Agent 是过度规定。
- 更简单实现：确定性计划 + schema 校验 + supervisor 可选。单 ADK Agent + 确定性工作流即满足 MVP。
- 保持 RED 的风险：低。MVP 场景可确定性分解。
- 结论：改写为能力需求，降为 AMBER（结构已有，缺 schema 与风险字段）。

### FR-004 Specialist Agent → Controlled Task Execution

- 真需要吗：是，但需要的是「执行只在授权工具/数据边界内」，不是 Specialist Agent。
- MVP 需要吗：是。
- 现状不足吗：`tool_grants` + `requires_approval` 已做工具边界；数据边界（data_classes → provider/工具）未执行。
- 目标是否过度规定：是，但能力本体（受控执行）不虚。
- 更简单实现：单 Agent + 工具授权 + 数据分类执行，无需多 Agent。
- 保持 RED 的风险：中。写操作越界。
- 结论：改写为能力需求，保持 AMBER，重点补数据边界执行。

### FR-005 Reviewer Agent → Result Validation

- 真需要吗：对高风险结果（L3 写）是。
- MVP 需要吗：是，但只需「结果校验」能力，不是 Reviewer Agent。
- 现状不足吗：无 validation 步骤类型，无来源/策略/完整性校验。
- 目标是否过度规定：是。
- 更简单实现：工作流里的 validation 步骤 + 策略/引用校验，无独立 Reviewer Agent。
- 保持 RED 的风险：中高。高风险结果无人复核。
- 结论：改写为能力需求，保持 Must，实现为 validation step，不强制 Agent。

### FR-002 多渠道 → Web + Task API（MVP），Teams 后置

- 真需要吗：Web 是。Teams 是目标，但不是 MVP 必需。
- MVP 需要吗：需要的是异步任务 API（`/v1/tasks`），让 Teams 以后能挂接。
- 现状不足吗：是。仅 Web 控制台，无 Task API，无 channel adapter。
- 更简单实现：Web 控制台 + 异步 Task API；Teams adapter 后置。
- 保持 RED 的风险：MVP 内低，前提是 Task API 先有。
- 结论：拆成两个能力，Task API 进 MVP，Teams 后置。

### FR-008 RAG → 保留 RED，提前到 MVP-1，但分两段

- 真需要吗：是。两个 MVP 场景都依赖知识检索与引用。
- MVP 需要吗：是，用于证明业务价值。
- 现状不足吗：是，整体缺失。
- 目标是否过度规定：是。目标规定完整 RAG 链（解析、分块、embedding、重排）。
- 更简单实现：第一段做「结构化数据检索 + 引用」（GSC 异常分析，数据在 DSS/CDP/SAP，多为结构化）；第二段再做「非结构化 RAG」（IT 支持 KB，SharePoint/文件）。先用 `RagService` 端口隔离。
- 保持 RED 的风险：高。没有 RAG 只能验证「平台能跑」，不能验证业务价值。
- 结论：保留 RED，进入 MVP-1，结构化检索优先于向量检索。

### FR-009 记忆 → 保留 RED，后置 P2

- 真需要吗：短期（session）已够 MVP；长期记忆不需要。
- MVP 需要吗：否。
- 现状不足吗：只有 ADK session。
- 保持 RED 的风险：MVP 内低。
- 结论：Should，保留 RED，P2。

### FR-010 模型路由 → 保留 RED，P1

- 真需要吗：是。MVP 验收明确要求「至少两个批准模型端点，验证路由与降级」。
- 现状不足吗：是。无 alias/路由/降级/预算。
- 更简单实现：alias + primary/fallback + 每租户预算，不做全量多路智能路由。
- 保持 RED 的风险：高。单点模型故障 + 无法证明模型可替换。
- 结论：保留 RED，P1，代码结构走 Policy → Alias → Gateway → Endpoint。

### FR-012 通知 → 保留 RED，后置 P2

- 真需要吗：MVP 内 HITL 在控制台内完成，通知非必需。
- 现状不足吗：只有审批回调（`approvals.py:372`）。
- 保持 RED 的风险：MVP 内低。
- 结论：Should，保留 RED，P2。

### FR-016 多语言 → 保留 RED，后置 P2，但 schema 留 locale 字段

- 真需要吗：中文优先即可满足首批场景；中英是加分项。
- 保持 RED 的风险：低（目标受众是企业内网中文）。
- 结论：Should，保留 RED，P2，但数据模型留 locale 字段避免返工。

---

## 4. MVP Scope Recommendation

把当前「平台 MVP」拆成两层，且明确：MVP-0 大部分已建成，真正的差距是信任边界加固 + 业务验证。

### MVP-0：Platform Foundation（现状 + 加固，不是从零建）

| 能力 | 现状 | MVP-0 动作 |
| --- | --- | --- |
| Identity / Session | 已有 OIDC、session | 收口角色模型（D-07） |
| Tool Catalog / Policy | `ToolEntry` 字段不足 | 补 schema/版本/owner/R-W/幂等 |
| HITL | 已有 | 补风险分级（D-06） |
| Model Abstraction | 已有 provider 适配 | 补 alias/路由（FR-010 进 P1） |
| Audit / Observability | 已有 | 补告警规则（Ops 配置，非代码） |
| Recovery / Versioning | 已有 checkpoint/生命周期 | 保持 |
| Trust Boundary | 缺失 | 网关策略服务端化（F-01/F-02） |

退出判据：伪造 `policy`/`grants` 被拒；角色默认不再 admin；写工具缺幂等键被拒。

### MVP-1：Business Validation（证明业务价值）

至少包含：1 个真实业务场景 + RAG（先结构化检索）+ 真实企业数据 + citations + 权限过滤 + 可度量 KPI。

- 首选场景：GSC 异常分析助手（数据多为结构化，RAG 门槛最低）。
- 退出判据：答案带可访问引用；越权文档/数据不可检索；高风险写操作 100% 过审批；KPI 可度量。

---

## 5. Authorization Pattern Recommendation

不设单一授权模式。按集成类型区分，但策略与审计模型统一。

| 集成类型 | 建议模式 | 理由 |
| --- | --- | --- |
| RAG / SharePoint | Service Identity + ACL enforcement | 索引器用服务身份读，ACL 元数据在摄取时绑定、查询时过滤。读路径无需用户委托 |
| Analytics / DSS / CDP（只读） | Service Identity + 下游 ACL / 行级过滤 | 只读 + 审计即可，MVP 可接受 |
| ServiceNow 建单 | Controlled Service Identity + 审计(user + agent) | 工单本身记录请求人；低风险可自动，关闭/重大变更走 HITL |
| SAP 读 | Service Identity + ACL | 只读 + 审计 |
| SAP 写 | Controlled Service Identity + HITL + 审计(user + approver + agent)；OBO 后置 | SAP 写是 L3，本就必须人工审批；受控服务身份 + 强制审批 + 全审计给出可接受的非抵赖，避免 MVP 就上 OBO 复杂度 |
| MES 写 | 双人审批 + Controlled Service Identity | 生产调整需双人或流程审批 |

关键架构点：执行下游调用的「身份模式」可变，但授权决策点（principal × resource × action × risk level × approval）与审计模型必须统一。OBO/委托身份进入 P2，当写操作量大或需无接触自动化时再上。

---

## 6. Proposed Priority Re-ranking

按「先把一个 Agent 安全可靠地完成任务做好，再谈多 Agent 协作」。

| 优先级 | 主题 | 内容 |
| --- | --- | --- |
| P0 | Trust Boundary | D-05 授权模式（按类型）、D-06 风险分级、D-07 角色模型、D-21 模型/数据分类准入、D-23 残余风险接受；代码侧：网关策略服务端化（F-01/F-02）、去掉 `--role admin` 默认 |
| P1 | Execution Control | 工具目录元数据、R/W 分类、幂等、超时、重试、审计、Kill Switch |
| P1 | Model Control | Model Alias → Routing Policy → Approved Provider → Fallback → Cost/Token/Trace |
| P1/P2 | Enterprise Knowledge | `RagService` 端口 + ACL 契约 → 结构化检索 + 引用 → 非结构化 RAG → 提示注入防护 → 知识新鲜度 |
| P2 | Agent Sophistication | Planner/Reviewer 作为能力（validation step）、长期记忆、多 Agent 优化 |

注：Observability 已建成（审计、指标、OTel），不列为构建项；差距是告警规则（运维配置），随 P1 一起补齐。

---

## 7. Decision Register Changes

1. **加「类型」列**，区分 Architecture / Security / Business / Operational / Engineering Decision。
2. **「建议默认」改为「Proposed Target」**，数字参数一律标 `Requires Owner Approval`，不得被后续当成已批准需求。
3. **D-01 拆分**为 MVP-0 / MVP-1，MVP-1 必须含一个真实业务场景 + RAG。
4. **D-05 拆分**为「按集成类型的授权模式」，不再单一默认。
5. **D-07 提到 P0**，与 D-05/D-06 并列，不排在 Planner 之后。

---

## 8. Acceptance Matrix Changes

1. FR-003/004/005 改写为能力需求（Structured Task Planning / Controlled Task Execution / Result Validation），实现形式不写死 Agent。
2. FR-002 拆为「Web + Task API（MVP）」与「Teams（后置）」。
3. FR-008 保留 RED，但标注进入 MVP-1，第一段结构化检索优先。
4. 支持度调整：FR-003 从 RED 改 AMBER（结构已有，缺 schema/风险字段）；FR-004 保持 AMBER（补数据边界）；FR-005 保持 RED 但实现为 validation step。
5. 所有「草拟测试用例名」保留，写 spec 时仍由 `scripts/check_specs.py` 校验真实存在。

---

## 9. Architecture Decisions Still Required

这些是进入 TO-BE 前必须产出的 ADR，缺一不可：

1. **ADR：网关策略服务端化**。模型网关与工具网关不再信任请求体里的 `policy`/`grants`，改为按 `agent_ref` 从注册表/授权存储读取。这是 Trust Boundary 的代码落点。
2. **ADR：风险分级模型**。`requires_approval: bool` → 风险等级 + 审批策略的映射（L1–L4）。
3. **ADR：角色与职责分离**。冻结平台角色目录，去掉 `--role admin` 默认，定义角色 → 能力映射。
4. **ADR：按集成类型的授权模式**。第 5 节的模式表，作为授权决策点与审计模型的基础。
5. **ADR：RagService 端口与 ACL 契约**。先定端口，再选向量库/embedding。
6. **ADR：模型别名与路由**。Model Alias → Routing Policy → Approved Provider → Fallback → Cost，含数据分类到 provider 的准入映射。

上述 ADR 与 D-05/06/07/13/21/23 一一对应。ADR 确认后，才进入 TO-BE 与切片。

---

## Revised Decision Register（候选，未替换原文件）

类型列：Arch（架构）/Sec（安全）/Biz（业务）/Ops（运营）/Eng（工程）。

| ID | 决策项 | 类型 | 阻塞 | Proposed Target | 状态 | 决策者 |
| --- | --- | --- | --- | --- | --- | --- |
| D-01 | MVP 拆 MVP-0 / MVP-1 | Biz | 硬 | MVP-0=平台加固；MVP-1=1 真实场景 + RAG + 引用 + 权限过滤 + KPI | Requires Owner Approval | PO |
| D-05 | 按集成类型的授权模式 | Arch | 硬 | 见第 5 节表，OBO 后置 P2 | Requires Owner Approval | Sec/Data + ERP |
| D-06 | 风险分级 L1–L4 | Arch+Sec | 硬 | 工具/动作 → 风险等级 → 审批策略 | Requires Owner Approval | Sec + Process Owner |
| D-07 | 角色目录与职责分离 | Arch+Sec | 硬 | 冻结 5 平台角色，去 `--role admin` 默认 | Requires Owner Approval | PO + Sec |
| D-08 | 租户粒度 | Arch | 软 | tenant=公司，部门放 attributes | Engineering Default | EA |
| D-09 | 审批 SLA / 升级 / 紧急覆盖 | Ops | 软 | 4h 超时升级、紧急停用双人 | Requires Owner Approval（参数） | Ops |
| D-10 | 首批系统清单与读写边界 | Biz | 软 | GSC 场景，SAP 只读，ServiceNow 建单自动 | Requires Owner Approval | ERP + System Owner |
| D-11 | 系统 API 规格/认证/限流/幂等 | Eng | 硬（工具目录） | 逐系统接入文档 | Requires Owner Approval | System Owner |
| D-12 | ACL 权威源与同步延迟 | Arch | 硬（RAG） | SharePoint 为权威，延迟容忍 ≤30min | Requires Owner Approval（参数） | Data Owner |
| D-13 | RagService 端口与 ACL 契约 | Arch | 硬（RAG） | 先端口后选型，向量库/embedding 走 ADR | Requires Owner Approval | Infra + Data/AI |
| D-14 | 保留/删除/导出 | Ops+Sec | 软 | 13 个月，可删可导出 | Requires Owner Approval（参数） | Legal + Sec/Data |
| D-15 | 评估集来源/标注/更新 | Biz | 软 | 场景 Owner 标注，每版本更新 | Requires Owner Approval | PO + Agent Dev |
| D-16 | 部署目标 | Ops | 硬（K8s 加固） | 企业 K8s 单集群多 namespace | Requires Owner Approval | Infra |
| D-17 | HA/DR 范围 | Ops | 硬（RTO/RPO） | 单区域 HA + 备份恢复，多区域后置 | Requires Owner Approval | Infra + PO |
| D-18 | 并发与成本预算 | Ops | 软 | 100 并发，月预算 | Requires Owner Approval（参数） | PO + Platform |
| D-19 | SLO/告警/值班/分级 | Ops | 软 | 成功率、P95、成本异常三条先上 | Requires Owner Approval | Ops |
| D-20 | 发布策略与回滚 | Ops | 软 | canary 10% / 30min | Requires Owner Approval（参数） | Ops + PO |
| D-21 | 模型供应商/区域/DPA/数据分类准入 | Sec | 硬（路由） | 至少两个批准端点，受限数据只进批准端点 | Requires Owner Approval | Sec/Data |
| D-22 | 新依赖审批 | Arch | 硬 | 向量库/Teams SDK/通知/OBO 各走 ADR | Engineering Default | EA |
| D-23 | 残余安全风险接受 | Sec | 硬 | 沙箱绕过/共享 token/跨租户 admin/无镜像签名逐条登记 | Requires Owner Approval | Sec |
| D-24 | 日志/审计 PII 与保留 | Sec | 软 | 日志脱敏，审计不记明文/密文 | Requires Owner Approval | Legal + Sec |

---

## Revised FR Acceptance Matrix（候选，未替换原文件）

| FR | 优先级 | 支持度 | 正例 | 反例 | 草拟测试用例名 |
| --- | --- | --- | --- | --- | --- |
| FR-001 身份与会话 | Must | GREEN | OIDC 绑定 tenant/roles/attributes 到 session | 无 token 或无 tenant 被拒 | `test_oidc_session_binding` |
| FR-002a Web + Task API | Must | AMBER | 异步任务创建/查询/取消/恢复 | 跨副本任务状态不一致 | `test_task_api_lifecycle` |
| FR-002b Teams 渠道 | 后置 | RED | Teams 消息路由到同一任务 | 跨渠道状态不一致 | `test_teams_channel_task` |
| FR-003 结构化任务规划 | Must | AMBER | 产出步骤 + 成功条件 + 风险分级 | 计划 schema 非法被拒 | `test_plan_schema_and_risk` |
| FR-004 受控任务执行 | Must | AMBER | 步骤只在授权工具/数据边界内 | 越权工具或越数据分类被拒 | `test_execution_boundary` |
| FR-005 结果校验 | Must | RED | 校验来源/策略/完整性/风险并退回/升级 | 无来源结论被退回 | `test_result_validation` |
| FR-006 工具调用与目录 | Must | AMBER | 目录含 schema/版本/Owner/超时/幂等 | 缺幂等键的写工具被拒 | `test_tool_catalog_metadata`、`test_tool_idempotency` |
| FR-007 HITL | Must | GREEN | 高风险写审批前不执行 | 审批超时/拒绝后不执行 | `test_approval_before_write` |
| FR-008 知识检索（MVP-1） | Must | RED | 答案带可访问引用 | 越权文档/数据不可检索 | `test_rag_acl_filter`、`test_rag_citation` |
| FR-009 记忆管理 | Should | RED | 分层读写删除 | 跨会话/跨用户串扰 | `test_memory_layer_isolation` |
| FR-010 模型路由 | Must | RED | 主模型故障降级且权限不变 | 受限数据进未批准端点被拒 | `test_model_fallback`、`test_data_class_provider` |
| FR-011 中断与恢复 | Must | AMBER | 暂停/恢复/取消/幂等重试 | 重复写不产生重复记录 | `test_plan_resume`、`test_idempotent_retry` |
| FR-012 通知 | Should | RED | 审批/失败/完成通知 | 通知失败不影响主流程 | `test_notification_outbox` |
| FR-013 运营控制 | Must | AMBER | 查看任务/trace/成本并停用 | 停用在途运行被取消 | `test_ops_console`、`test_kill_switch` |
| FR-014 配置与版本 | Must | AMBER | Agent/Prompt/Model/Tool/Policy 版本化关联发布 | 未签名/不匹配发布被拒 | `test_publish_verification` |
| FR-015 反馈与评估 | Must | AMBER | 反馈落库进入评估闭环 | 无关联任务反馈被拒 | `test_feedback_loop` |
| FR-016 多语言 | Should | RED | 中英输入输出，术语映射 | 时区/数字按区域呈现 | `test_i18n_locale` |
