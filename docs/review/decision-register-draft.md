# 决策登记表（草稿）

状态：草稿，待评审确认。不是 ADR，不接受前不进入实现。
依据：现有代码（`master` @ `7cf1398`）与目标文档 `docs/specs/ADK_Agent_Product_Architecture_Specification_v1.0.docx`。
建议默认是我（评审代理）基于现状的推荐，供 Owner 修改。

## 阻塞级别定义

| 级别 | 含义 |
| --- | --- |
| 硬阻塞 | 不决策就无法正确实现对应切片，先做会返工 |
| 软阻塞 | 可以先实现端口/骨架，后填具体值，但有返工风险 |
| 后置 | 不影响当前切片，可在后续阶段定 |

## 1. 范围与验收

| ID | 决策项 | 阻塞 | 建议默认 | 依据 | 决策者 |
| --- | --- | --- | --- | --- | --- |
| D-01 | MVP 的 FR 清单与 in/out 边界 | 硬 | FR-001/004/006/007/010/011/013/014 进 MVP；FR-002 Teams、FR-008 RAG 跟随后 | 目标文档 6.1 全部标 Must，一次做全会拖长 | Product Owner |
| D-02 | 每个 FR 的可验证验收用例 | 硬 | 每 FR 至少 1 正例 1 反例，写入 `docs/review/fr-acceptance-matrix-draft.md` | spec 引用用例名须真实存在（`scripts/check_specs.py`） | PO + Architect |
| D-03 | 两个 MVP 场景的业务 KPI 与基线 | 软 | 人工节省时间、一次解决率、越权事件为 0 | 目标文档 3.2 MVP 退出标准 | PO + Process Owner |
| D-04 | UAT 环境、样本数据、签字人 | 软 | 复用 SIT，样本脱敏，PO 签字 | 目标文档 14 环境表 | PO + Operations |

## 2. 授权与风险模型

| ID | 决策项 | 阻塞 | 建议默认 | 依据 | 决策者 |
| --- | --- | --- | --- | --- | --- |
| D-05 | 用户权限透传到工具/检索的方式 | 硬 | 服务账号 + ACL 元数据过滤；OBO/代币交换后置 | 连接器现在用服务凭据 `auth_ref`（`core/connectors.py:48`），无 OBO | Security/Data + ERP |
| D-06 | L1–L4 风险分级到工具/动作的映射 | 硬 | 按工具读写 + 影响面做 4 级表 | 现在是布尔 `requires_approval`（`core/policy.py:17`），表达不了分级 | Security + Process Owner |
| D-07 | 角色目录与职责分离 | 硬 | 冻结 5 个平台角色；业务角色后置 | 角色是自由字符串，`--role` 默认 admin（`cli.py:1436`） | PO + Security |
| D-08 | 租户粒度（公司/部门/业务线） | 软 | tenant=公司，部门放 principal attributes | `Principal.attributes` 已存在（`core/identity.py:17`） | Enterprise Architecture |
| D-09 | 审批 SLA、升级路径、紧急覆盖 | 软 | 审批 4h 超时升级；紧急停用需双人 | 审批已有 `expires_at`（`core/approval.py:25`），无升级/覆盖 | Operations |

## 3. 系统与数据接入

| ID | 决策项 | 阻塞 | 建议默认 | 依据 | 决策者 |
| --- | --- | --- | --- | --- | --- |
| D-10 | 首批系统清单与读写边界 | 软 | GSC 场景 DSS/CDP 只读、SAP 只读、ServiceNow 建单自动 | 目标文档 10 目标系统表 | ERP/Integration + System Owner |
| D-11 | 各系统 API 规格、认证、限流、幂等语义 | 硬（工具目录） | 逐系统一份接入文档 | 没有这些，工具目录 Owner/版本/幂等字段只能空着 | System Owner |
| D-12 | ACL 权威源与同步延迟容忍 | 硬（RAG） | SharePoint 权限为权威，同步 ≤30min | 目标文档 11.2 知识更新延迟 | Data Owner |
| D-13 | 向量库与 embedding 选型、部署位置 | 硬（RAG） | 新 ADR，先定 `RagService` 端口与 ACL 契约，厂商后选 | 项目规则：新依赖须过 ADR | Infrastructure + Data/AI |
| D-14 | 数据保留期、删除流程、审计导出格式 | 软 | 保留 13 个月，可删可导出 | 目标文档 11 Conversation Record 可导出/删除 | Legal + Security/Data |
| D-15 | 评估集来源、标注人、更新频率 | 软 | 场景 Owner 标注，每版本更新 | NFR-009 与 FR-015 依赖度量 | PO + Agent Dev |

## 4. 平台与运维

| ID | 决策项 | 阻塞 | 建议默认 | 依据 | 决策者 |
| --- | --- | --- | --- | --- | --- |
| D-16 | 部署目标（K8s 发行版、云/自建、网络分区） | 硬（K8s 加固） | 企业 K8s，单集群多命名空间 | 现有清单是多副本示例（`deploy/k8s/multi-replica.yaml`） | Infrastructure |
| D-17 | 可用性与 HA/DR 范围 | 硬（RTO/RPO） | 单区域 HA + 备份恢复；多区域后置 | 目标 NFR-001/006，单区域与多区域差一个量级 | Infrastructure + PO |
| D-18 | 并发与成本预算 | 软 | 先 100 并发，按月预算 | NFR-004 100→1000，需分步 | PO + Platform |
| D-19 | SLO、告警阈值、值班与事件分级 | 软 | 先上成功率、P95、成本异常三条 | 目标文档 16.1 告警阈值建议 | Operations |
| D-20 | 发布策略与回滚时限 | 软 | canary 10% 观察 30 分钟 | 目标文档 15 Post-release canary | Operations + PO |

## 5. 治理与风险接受

| ID | 决策项 | 阻塞 | 建议默认 | 依据 | 决策者 |
| --- | --- | --- | --- | --- | --- |
| D-21 | 模型供应商清单、区域、DPA、数据分类准入 | 硬（模型路由） | 至少两个批准端点，受限数据只进批准端点 | 目标文档 9 数据分类策略；现在只有 provider allowlist | Security/Data |
| D-22 | 新依赖审批清单 | 硬 | 向量库、Teams SDK、通知、OBO 各走 ADR | 项目规则：禁止未经 ADR 新增依赖 | Enterprise Architecture |
| D-23 | 残余安全风险接受 | 硬 | 沙箱绕过、共享 token、跨租户 admin、无镜像签名逐条登记接受人 | 见 `docs/PROGRESS.md` 已知缺口与评审 F-05/F-07 | Security |
| D-24 | 日志/审计中的 PII 与保留 | 软 | 日志脱敏，审计不记明文与密文 | `logsafe.py` 已做 CRLF 转义，无 PII 语义脱敏 | Legal + Security |

## 最小启动包

不必等 24 项全定。先定这 6 项即可启动 P0/P1：

1. D-01 MVP FR 清单冻结。
2. D-05 授权透传模型选默认。
3. D-06 + D-07 风险分级与角色目录初版。
4. D-16 + D-17 部署目标与 HA 范围。
5. D-21 批准模型端点与数据分类准入。
6. D-23 残余风险接受人。
