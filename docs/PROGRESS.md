# 项目进度登记

更新日期: 2026-11-26
分支: master（工作区干净，只留本地工具目录未跟踪）
最新提交: `d74c5b9` feat: run the support demo through a human-approved plan step (SLICE-304) (#355)
状态: 进行中；M6 Enterprise Trust Chain 已收口；ADR-0031、0033、0035、0036、0037、0038 交付；ADR-0038（语义层）MVP 五个切片（SLICE-217 到 221）已全部交付闭环；ADR-0039（控制台全平台能力总览与 Ask AI 入口）MVP 七个切片（SLICE-222 到 228）已全部交付闭环；ADR-0040（全局默认模型）MVP 已关闭；ADR-0041（控制台 Vue 产品化）阶段 0 已收口（SLICE-236 脚手架 + SLICE-237 路由/Pinia/鉴权流 + SLICE-238 总览 + SLICE-239 注册表 + SLICE-240 工具目录 + SLICE-241 工具授权 + SLICE-242 审批 + SLICE-243 审计 + SLICE-244 模型 + SLICE-245 配额 + SLICE-246 检索 + SLICE-247 语义层 + SLICE-248 连接器 + SLICE-249 凭据 + SLICE-250 对端 + SLICE-251 运行 + SLICE-252 会话 + SLICE-253 计划 + SLICE-254 策略 + SLICE-255 导入 + SLICE-256 Ask AI + SLICE-257 Chat 全部交付）；阶段 1（用户/角色/授权 + 统一登录）已收口（SLICE-258 角色定义 store、SLICE-259 用户绑定 store、SLICE-260 能力解析运行时化、SLICE-261 角色/用户管理接口、SLICE-262 用户绑定并入能力解析、SLICE-263 用户/角色管理面板已交付；**阶段 1 收口**）；阶段 2（Agent 中心总览）已收口；阶段 3（安全合规聚合视图）已收口；阶段 4（MCP/API 生态展示）已收口；阶段 5（Agent 开发向导 + 页面一键发布，ADR-0043）已收口（SLICE-280 compose 后端、SLICE-281 向导）；ADR-0044（载入侧构建签名）已交付（SLICE-291）；ADR-0045 四个切片全部交付：方案 A 记录（SLICE-296）、方案 B 只写密钥（SLICE-297）、运行时解析（SLICE-298）与控制台「模型」页表单和手册（SLICE-299）。

## 本次暂停交接

- 代码在 `master`，`d74c5b9`。SLICE-113 到 304 已合并，ADR-0041 阶段 0 到 5 全部收口，ADR-0043（控制台 compose 签名与页面一键发布）已交付，密钥运维手册已补；没有打开的实现 PR（记录型 PR 除外）。第 16 条列出的旧缺口已全部修完，剩余的是第 16 条末尾记录的新观察项。工作区干净，未跟踪的 `.agents/`、`.claude/agents/`、`.claude/skills/`、`.claude/worktrees/`、`package.json`、`package-lock.json`、`docs/review/*.docx`、`docs/specs/*.docx` 与两件未入库的 prove 输出（`docs/evidence/prove-2026-11-22-ui.txt`、`prove-2026-11-23.txt`）是本地工具与评审输入，不入库。
- 最近门禁: `--full` 9 步全 PASS，2382 passed, 105 skipped（在 SLICE-304 分支复跑；skip 来自本机 Windows 无法建符号链接与无 `TEST_POSTGRES_URL`）。
- 端到端验收: `python scripts/prove_it_works.py` 14 项真实进程/真实 Postgres 检查，2026-11-25 在 `24a4f7d`（SLICE-295）跑出 14/14 PASS（`docs/evidence/prove-2026-11-25-s295.txt`，`NO_PROXY=127.0.0.1,localhost`，litellm 1.106.2）；更早的 14/14 见 `prove-2026-11-25.txt`（SLICE-280 修复轮）；更早的 12/12 记录见 `docs/evidence/prove-2026-11-21.txt`、`prove-2026-11-22.txt`，复盘见 `docs/reviews/retrospective-2026-11-21.md`。
- v0.1.0 已于 2026-11-18 发布: tag `v0.1.0` 指向 `2406b9a`，GitHub Release 由用户从仓库根目录创建；本地镜像 smoke 通过（`/healthz` 200，`POST /mcp` 无 token 401、带 token 200），镜像未推送 registry。
- 治理规则已改为切片级自动：spec 到合并不再逐次确认，合并前必须有独立只读验证代理。
- M6 已收口：Gate 1（ADR-0030 角色职责分离）、Gate 2/3（ADR-0028 网关策略服务端化）、Gate 4（ADR-0029 风险分级 L1–L4 + ADR-0034 写工具幂等）。Gate 5 是端到端 trace 验证，随前四项一起闭环（审计 trace_id 与 OTel trace_id 已对齐）。
- ADR-0035（向量后端）已于 2026-11-20 会话确认 Accepted：Postgres + pgvector、embedding 复用 LiteLLM 通道、模型与维度由部署配置决定。slice 1-5 全部交付（pgvector 表与 RLS 检索、embedding 端口与带预算的网关、摄取管线、`PgVectorRagService` 检索、运维手册）；四个 live 用例需 `TEST_POSTGRES_URL`，pgvector SQL 与真实 LiteLLM embedding 调用尚未联网验证（运维验收项）。
- 后续（M6 之外）: ADR-0031、ADR-0033、ADR-0035、ADR-0036、ADR-0037 全部交付；RAG 摄取与检索已由 SLICE-194/195 接到 CLI，运行时预取与审计由 SLICE-197/198 交付，控制台与触发接线由 SLICE-199 交付。ADR-0037（审计链按存储内容哈希）由 SLICE-201 到 203 交付。已接受 ADR 的缺口清单只剩第 16 条列出的既有小项。
- 恢复顺序: 读 `CLAUDE.md`、`docs/specs/ROADMAP.md`、本文件，跑 `./.venv/Scripts/python.exe scripts/check.py --fast`，再从缺口清单挑一项。

## 一句话

企业级 ADK agent 平台的 M0 到 M5 已全部收口，另加控制台可见性、审计客户端接入、只读运营视图、OIDC 解析器、控制台 OIDC 接线、服务面 OIDC 接线、MCP HTTP 认证、MCP principal 注入、共享配额、审批收件箱、MCP 运行审计、指标与 trace、A2A 运行审计、审批过期、服务指标端点、审批归档、配额行级隔离、审计轮转签名、模型熔断、文件状态备份恢复、压测基线、SSE 有界缓冲、入口限流、MCP/A2A 限流、审计密钥轮换、可选的会话租户隔离和审计只读查询和控制台共享审计、工件类型、工件存储、带签名发布、验签加载、注册表启动和市场视图、Postgres 注册表、控制面、命令接线、按需加载、报告集中存储、工具目录、生命周期存储与拦截、工具授权请求存储与 MCP/A2A 工具守卫与临时授权合并、审批入口、用量视图、卸载置换、跨副本限流、连接器存储、连接器执行、控制面、工具目录合并、健康检查、A2A peer 身份、管理面、迁移收口、远端目录记录、市场页合并、出站审计、审计 Postgres 存储与数据库接线、审批 Postgres 收件箱与接线、多副本清单与运维手册、发行完整性八十八个切片。本地门禁全绿。OIDC 身份链路完整，多副本配额在 Postgres 上共享并由 RLS 约束，审批可以跨进程走通并有截止时间和归档，MCP 和 A2A 调用都有审计和配额，控制台、两个网关和 MCP 都有 Prometheus 指标，trace 能跨边界传播，审计链支持分段和 HMAC 验签，模型 provider 有熔断，注册表和审计可以打包备份并安全恢复，配额与审计吞吐有可复现的压测基线，控制台 SSE 在慢客户端下内存有界且会报告丢弃数，控制台、三个独立服务、MCP 和 A2A 都按调用方限流，审计签名密钥可轮换而不作废旧记录，会话可以按租户隔离，审计服务可按租户查询事件，控制台的审计与运行面板读同一份共享数据，工件可按 digest 存在文件或 Postgres，发布时可用 Ed25519 签名，注册的工件可按引用验签加载成 agent，控制台与 MCP 可直接从注册表启动，市场页显示工件摘要与验签状态，并附演示种子与截图，已发布版本可从共享 Postgres 读写而不依赖共享卷，控制面服务按契约发布、读取并接收工件字节，四个命令可用 `--registry-url` 读写同一份目录，市场页可按需验签加载版本并直接开聊，评测报告与版本同库并由控制台跨副本读取，工具目录可按租户展示来源、数据分级和授权关系。ADR-0010 已签字，生命周期状态可存储、读取与审计，退役版本无法再被加载或启动。ADR-0011 已签字，工具临时授权请求可存储、审批与到期判断，MCP 与 A2A 运行路径也按允许清单拦截工具，已批准的临时授权可按版本合并放行，控制台与 CLI 可申请、审批并留痕，Grants 面板显示用量与即将到期，按需加载的版本可卸载并同位置换。ADR-0012 已签字，限流计数可走 Redis 跨副本共享并在故障时回退。ADR-0013 已签字，连接器可注册、按租户列出并停用，并能在工具网关里按出站策略执行，控制台与 CLI 也能管理连接器，工具目录会显示已启用连接器及其授权版本，连接器可主动探测并给出结构化健康结论。ADR-0014 已签字，A2A 提供方按 peer 身份认证并按 `read`/`invoke` 授权，审计身份随 peer，legacy 共享单 token 模式保留且与 peer 模式互斥，peer 与授权可在控制台和 `peers` 命令里管理，两种模式的互斥有库层与 CLI 双重验证，迁移步骤见 `docs/guides/a2a-peer-migration.md`。远端 peer 暴露的 agent 可作为目录记录登记，card 摘要固定后刷新会区分固定、已变化与不可达，但暂不可从控制台加载；市场页会显示来源与信任徽标，并提供刷新入口。ADR-0015 已签字，消费者出站调用按 `a2a.call` 与 `egress=third_party` 审计，跨组织审计边界只覆盖本地侧，按 trace id 关联。ADR-0016 已签字，审计可按租户写入 Postgres、并发写安全并可整链验证。审计服务、控制台与网关可用 `--audit-db`/`AUDIT_DATABASE_URL` 共享同一份 Postgres 审计，`serve-audit` 文件与数据库双后端均可用。ADR-0017 已签字，审批请求与决定可按行存入 Postgres，条件 `UPDATE` 保证并发决策只生效一次，过期判定、归档与删除语义对齐文件实现，控制台、CLI prune 与执行器已共享同一份审批，两个进程的轮询与决策验证通过。Phase E 已收口，四个无本地卷的 Deployment 可多副本运行，运维手册覆盖环境变量、扩缩容、备份恢复、密钥轮换、时钟与故障处理。ADR-0018 已签字，运行时与开发依赖锁定为带哈希的集合，CI 按锁安装后构建并扫描镜像，SBOM 随构建产出，部署按 digest 引用；两条扫描接受风险带到期日。SLICE-102 把构建后端锁进依赖集合并把 CI action 固定到 commit SHA。ADR-0019 与 SLICE-103/104 让 Postgres 会话表启用并强制 RLS，租户取自已认证 principal，策略由 `sessions enable-rls` 显式安装，运维手册覆盖启用、回滚与排障。ADR-0020 与 SLICE-105/106 把 `app_states` 纳入同一租户边界，`app_name` 带租户前缀，四张表都由 RLS 强制，手册写明旧数据不自动迁移。SLICE-107 让密钥扫描覆盖证据目录并改用已审基线，过期接受风险不再被忽略。SLICE-108 让门禁只读基线，新命中不会被扫描命令写进允许清单。SLICE-109 补齐手动发布流水线与 digest 回写，首次真实推送给操作员执行。SLICE-110 让运行、模型、工具与 A2A 调用以 OTel span 导出，审计 trace_id 与 OTel trace_id 对齐。SLICE-111 让单与顺序计划按步骤落检查点，恢复时跳过已完成步骤，审批等待可恢复。SLICE-112 在模型网关上加了输入输出护栏，PII 脱敏与提示注入阻断，审计只记规则 id 与哈希。SLICE-113 给控制台加了浏览器 OIDC PKCE 登录与三组导航的应用外壳，token 与客户端 secret 不进入浏览器。SLICE-114 把 Runs 与 Plans 的 trace 升级为相对时间瀑布，失败与拒绝分色。SLICE-115 把审批面板做成工作台，截止时间可见、可过滤，并按理由决定。SLICE-116 把 Registry 面板做成卡片，来源、信任、评测与生命周期徽标统一色调，卡片可点击与键盘选中。SLICE-117 让控制台按服务端能力清单显示导航、面板与操作按钮，未知角色回到基础视图，无权深链自动回退。SLICE-118 让审批历史覆盖已决、已过期与已归档记录，文件与 Postgres 语义一致，控制台可按状态过滤。SLICE-119 让 trace 节点带审计字段，瀑布行可点击与键盘选中，Runs 与 Plans 显示 span 详情。SLICE-120 在日志记录工厂层集中转义 CR 与 LF，控制台启动即生效，收敛 CodeQL 的 29 条 log-injection。SLICE-121 增加租户凭据引用绑定，记录只含元数据，引用按租户映射到 `ADK_SECRET_<TENANT>_<NAME>`，控制台与 CLI 可登记、列出与停用，连接器登记要求同租户启用绑定，工具网关按租户作用域取用。SLICE-122 增加连接器自助申请与审批，租户提交申请，管理员批准时重查凭据并登记连接器，文件与 Postgres 单赢家决定，申请与决定写审计。SLICE-123 增加声明式组合器，`single-llm` 模板按参数生成确定性工件，参数只用 `repr` 嵌入，平台密钥签名后走既有评测、注册表与工件存储，组合结果可按 pinned 引用验签加载。SLICE-124 增加定时与 webhook 触发定义，pinned 到 agent 版本，webhook 令牌只存哈希，文件与 Postgres 双存储，CLI 可登记、列出与停用。SLICE-125 增加 webhook 执行服务，`serve-triggers` 按触发令牌哈希认证，pinned 版本验签加载，按租户配额与审计运行，幂等键单赢家，需审批工具的 agent 直接拒绝。SLICE-126 增加共享 `safe_join`，所有文件存储先做路径段白名单校验，再检查解析后的目标仍在存储根目录下。SLICE-127 增加调度循环与重试，schedule 触发按 slot 幂等键单赢家，webhook 与调度共用执行路径，预运行加载失败按次数退避重试，agent 启动后不重试。可做内部试点，未达对外多租户生产标准。ADR-0028 到 0034 已 Accepted，落地 M6 Enterprise Trust Chain：网关策略服务端化、风险分级 L1–L4、角色职责分离、按集成类型授权、RagService 端口与 ACL、模型别名路由、写工具幂等。SLICE-163 交付 Gate 1，`--role` 缺省从 admin 收紧到 requester，admin 能力必须显式声明或经 OIDC claim；15 个既有测试文件显式化 admin 角色（只改输入不改断言）。SLICE-164 交付 Gate 3，模型网关不再信任请求体 policy：`ModelGatewayRequest.policy` 改可选，`/v1/complete` 按 agent_ref 从注册表解析 `manifest.model_policy`，缺权威 fail-closed 403，注册表不可达 503；`serve-model-gateway` 新增 `--registry-url`/`--registry`。SLICE-165 交付 Gate 2，工具网关不再信任请求体 grants：`invoke()` 按 agent_ref 从注册表解析 manifest `tool_grants` 并从 `ToolGrantStore` 读临时授权，缺权威 fail-closed 403、权威不可达 503；`serve-tool-gateway` 新增 `--registry-url`/`--registry`/`--tool-grants-dir`。SLICE-166 交付 ADR-0028 slice 4 逃生门：`--trust-caller-policy` 回环开发专用、默认关闭，与 `--registry`/`--registry-url` 硬互斥。至此 ADR-0028 四个切片全部交付。SLICE-167 交付 ADR-0029 slice 1：新增 `RiskLevel = Literal["L1","L2","L3","L4"]` 与 `ToolGrant.risk_level` 可选字段，重生成契约 schema。SLICE-168 交付 ADR-0029 slice 2：`risk_level` 扩展到 `ToolEntry`/`PlanStep`/`ConnectorSpec`。SLICE-169 交付 ADR-0029 slice 3：`PlanStep.needs_approval` 计算属性按 `risk_level` 推导审批，`PlanExecutor` 两处审批门改用该属性，`AuditEvent` 携带 `risk_level`，重生成 `audit_event.schema.json`。SLICE-170 交付 ADR-0029 slice 4：`GrantPolicyEngine` 在授权决策点对 `risk_level="L4"` 的 manifest 授权默认拒绝（`error_code=l4_default_deny`），同一 tool_id 取最高风险等级 fail-closed，契约 `tool_gateway.md` 记录该语义。ADR-0029 四个切片全部交付。SLICE-171 交付 ADR-0034 slice 1：`ToolSpec`/`ToolEntry` 增加 `write`/`idempotency_required` 字段与 `requires_idempotency` 计算属性（写工具默认要求幂等），无对外 schema 变更。SLICE-172 交付 ADR-0034 slice 2 前半：`ToolRequest` 增加 `idempotency_key`，写工具缺 key 由工具网关返回 400 `idempotency_missing` 并审计，重生成 `tool_gateway_request.schema.json`。SLICE-173 交付 ADR-0034 slice 2 后半：`ToolExecutionRecord`（`claimed`/`completed`/`unknown` + TTL）与 `ToolIdempotencyStore` 协议，文件（`sha256(key)`+`os.link` 单赢家）与 Postgres（`ON CONFLICT DO NOTHING` 单赢家）双实现。SLICE-174 交付 ADR-0034 slice 3：工具网关按 `idempotency_key` 去重——claim→execute→finish，重复 `completed` key 重放旧结果、`unknown`（序列化失败）重试返回 502 不重执行、并发在途返回 409；`ToolExecutionRecord` 增加 `claim_id` 区分赢家。SLICE-175 交付 ADR-0034 slice 4：`ToolSpec` 增加 `risk_level`，`idempotency_required` 改三态，`requires_idempotency` 按 L3/L4 强制、否则显式值、否则回落 write。SLICE-176 交付 ADR-0034 收尾：存储增加 `release`，工具执行抛异常时 best-effort 释放 claim，使瞬时失败可重试。SLICE-177 交付 ADR-0034 CLI 接线：`serve-tool-gateway` 增加 `--idempotency-dir`/`--idempotency-db` 并把存储传给网关。ADR-0034 至此全部交付，M6 Enterprise Trust Chain 收口。SLICE-178 交付 ADR-0031 slice 1：`ConnectorSpec` 增加 `delegation` 字段（`service`/`controlled-service`/`obo-later`，缺省 `service`），导出 `DelegationMode`，契约 `connector_requests.md` 补充说明。SLICE-179 交付 ADR-0031 slice 2：`ToolSpec`/`ToolEntry` 增加 `delegation`，`build_connector_tools`/`connector_tool_entries` 把连接器 `risk_level`/`delegation` 传播到工具暴露面，使决策点能看到连接器元数据。SLICE-180 交付 ADR-0031 slice 3：`ToolSpec`/`ToolEntry` 增加 `needs_approval`（`requires_approval or risk_level in ("L3","L4")`），工具网关审批门改用该属性，使 L3/L4 工具（含 SAP/MES 写）强制 HITL。SLICE-181 交付 ADR-0031 slice 4：`docs/guides/obo-deferral.md` 说明 OBO 后置现状、引入条件与新 ADR 门槛。ADR-0031 四个切片全部交付。SLICE-182 交付 ADR-0032 slice 1：`src/adk_agent/rag/` 新增 `Citation` 类型与 `RagService` 协议，`docs/contracts/rag_service.md` 记录 ACL 契约，`.importlinter` 把 `rag` 加入 core 禁止导入清单。SLICE-183 交付 ADR-0032 slice 2：`rag/memory.py` 新增 `RagSource`/`InMemoryRagService`，实现 ACL + data_classes + 查询过滤的结构化检索，返回 `acl_checked=True` 引用。SLICE-184 交付 ADR-0032 slice 3：`rag/guard.py` 新增 `detect_prompt_injection` 与 `RagGuard`（低置信度 + 注入模式过滤，fail-closed），`InMemoryRagService` 可选接入。SLICE-185 交付 ADR-0033 slice 1：`ModelCandidate`/`ModelAlias` + `ModelPolicy.model_aliases` + `AgentManifest.model_alias`，`manifest_digest` 对缺省新字段向后兼容（存量记录 digest 不变），重生成两个契约 schema；经用户确认更新了 `test_execution_tier.py` 的 digest 辅助函数（断言未动）。SLICE-186 交付 ADR-0033 slice 2：`models/routing.py` 的 `resolve_candidates`（按 allowlist 与数据分类准入过滤、保序），网关 `complete(alias=, data_classes=)` 按序尝试、主候选失败降级、策略拒绝不降级、全败抛 `ModelUnavailable`。SLICE-187 交付 ADR-0033 slice 3：`models/budget.py` 的 `BudgetTracker`（按租户累计 USD），网关调用前检查 `policy.budget_usd`（超限审计 `budget_exceeded` 并拒绝，降级不可绕过），成功后累计 `cost_usd`。SLICE-188 交付 ADR-0033 slice 4：`AuditEvent` 增加 `model_alias` 与 `fallback_count`，每次尝试都记录 alias 与降级序号，重生成审计两个 schema。ADR-0033 四个切片全部交付。ADR-0035 经 2026-11-20 会话确认 Accepted：向量存储选 Postgres + pgvector、embedding 复用 LiteLLM 通道、模型与维度由部署配置决定。SLICE-189 交付 ADR-0035 slice 1：`rag/vector_store.py` 新增 `adk_rag_chunks` 表（租户 RLS、`data_classes`/`allowed_subjects` ACL 列、`vector(N)` 向量）与 `PgVectorRagStore` 的 upsert/近邻检索，维度或驱动错误一律 fail-closed；与 ADR 草案 `acl jsonb` 的偏差已记入证据。SLICE-190 交付 ADR-0035 slice 2：`EmbeddingRequest`/`EmbeddingResponse` 与 `EmbeddingProvider` 协议，`LiteLlmProvider.embed` 复用同一通道，`EmbeddingGateway` 在调用前做允许清单与租户预算检查（超限拒绝不降级），成功后累计成本并写 `model.embed` 审计。SLICE-191 交付 ADR-0035 slice 3：`rag/ingest.py` 新增 `split_text` 与 `IngestionPipeline`（分块→embed→带 ACL 的 upsert，空文本拒绝、embedding 失败不部分写入），并写明租户与 subject 可见性语义。SLICE-192 交付 ADR-0035 slice 4：存储返回余弦距离，`PgVectorRagService` 嵌入查询、按 principal 的 ACL 搜索、把距离映射为置信度并应用 `RagGuard`，缺 invocation/policy 拒绝。SLICE-193 交付 ADR-0035 slice 5：运维手册新增「RAG 向量存储（pgvector）」一节，覆盖扩展安装与角色权限、RLS 强制、维度与重建索引、HNSW 建索引与 REINDEX、`RagStoreUnavailable` fail-closed 与多副本共享；三轮独立验证发现的 DML-only 与并发首启误述均已按代码事实修正。ADR-0035 至此五个切片全部交付。SLICE-194 交付 RAG 的 CLI 接线：`adk-agent rag ingest` 与 `rag search` 复用既有 `IngestionPipeline` 与 `PgVectorRagService`，嵌入走带预算与审计的 `EmbeddingGateway`；契约先改 `docs/contracts/cli.md`，13 个用例覆盖写入、空输入、存储不可用、审计、预算、ACL 透传与 help。SLICE-195 收尾 RAG 命令行：`rag ingest --dir` 批量摄取（相对路径 `source_id`、跳过符号链接与空文件、按相对路径字符串排序）、缺 `litellm` extra 时给安装提示、`--data-class` 取值改为从 `DataClass` 推导。SLICE-196 交付 ADR-0036 slice 1：`AgentManifest.rag`（`RagConfig`：`enabled`/`top_k`/`min_confidence`/`data_classes`/`on_error`），`rag=None` 不进摘要载荷，存量 digest 不变，重生成 `manifest.schema.json`。SLICE-197 交付 ADR-0036 slice 2：`rag/context.py` 的 `RagContext` 做运行时预取与固定边界注入（`acl_checked` 过滤、`RagGuard`、`top_k` 截断、Cf 类字符剔除与边界/编号中和），`AgentRuntime` 增加可选 `rag` 并把预取放进受审计的 try，`deny`/`degrade` 两种失败语义。SLICE-198 交付 ADR-0036 slice 3：`AuditEvent` 增加 `rag_top_k`/`rag_returned`/`rag_filtered`（未使用时 `exclude_if` 不序列化，历史审计链哈希不变），`RagContext` 每次预取写一条 `rag.retrieve`，失败先审计再按 `on_error` 抛或继续，事件只含计数、状态、延迟与数据分级。SLICE-199 交付 ADR-0036 slice 4 接线：`RagFactory` 共享 pgvector 存储与嵌入网关，按 manifest 的 `rag` 块构造 `RagContext`；`console` 在按需加载时接线、`serve-triggers` 每次执行按 pinned 记录接线，两个命令新增 `--rag-db/--rag-dimensions/--rag-model/--rag-provider`。SLICE-200 交付 ADR-0036 收尾：运维手册补「运行时检索」（参数、生效范围、审计、预算归属、缺口与升级回滚），使用手册补「检索（RAG）」（manifest 示例、装料、自检、开启、上下文块形态），并修正验证指出的五处误导表述。ADR-0036 五个切片全部交付。ADR-0037 经 2026-11-21 会话确认 Accepted：不重写历史、保留 `exclude_if`、不为 Postgres 增加 `event_json` 列。SLICE-201 交付 ADR-0037 slice 1：文件审计链按**存储的事件 JSON** 归一化后哈希（新增 `canonical_event_json`，负零折叠，`record_hash` 接受事件对象/JSON 文本/映射），新增 `docs/contracts/audit_chain.md` 记录记录结构与哈希口径。SLICE-202 交付 ADR-0037 slice 2：Postgres `verify-audit` 按存储的 `event::text` 重算哈希（jsonb 往返保真已用 live 库实测），`_walk` 同时保留可解析性校验，负零用例补齐。SLICE-203 交付 ADR-0037 slice 3：运维手册「值守检查」写明校验口径以存储内容为准，区分「能被规范形式复现、升级后恢复正常」与「存储内容与 hash 已对不上、仍按断链调查」两类记录，并给出定位与处置；两轮独立验证指出的历史记录过度声明与弱断言均已收敛。ADR-0037 三个切片全部交付。SLICE-204 修复控制台启动引用不检索：注册表加载的 agent 携带 `_adk_manifest`，启动注册时据此构造 `RagContext`；`--agents` 文件加载仍不检索，按需加载不变；端到端验收 P7 改走启动引用路径。SLICE-205 执行 `model_allowlist`：空列表不限制，非空时直连、别名候选与 `GatewayLlm` 都检查；直连拒绝审计 `model_not_allowed`，别名无候选审计 `alias_not_allowed`；ADR-0033 与手册写明 console 合成策略不含 manifest allowlist 的边界。SLICE-206 把检索接到 MCP 与 A2A：`serve`/`serve-many`/`serve-a2a` 接受 `--rag-*`，`AuditedRunner` 预取并注入首条消息，只给检索也会包代理；契约先改 `docs/contracts/cli.md`；端到端 P5/P6 验证标记进入回复且 `rag.retrieve` 各 +1。SLICE-207 让沙箱化触发也检索：配额预留后、沙箱运行前按 pinned manifest 预取并拼输入，检索失败在沙箱与非沙箱两条路径都映射 `rag_unavailable`（500），错误码表与手册同步；沙箱后端仅 POSIX，接线由假后端用例覆盖。SLICE-208 在服务入口校验检索维度：`--rag-dimensions` 为 0 或负数时打印提示并退出 1，不再让 `RagStoreUnavailable` 以 traceback 冒出；`rag ingest`/`rag search` 与 `PgVectorRagStore` 的既有拒绝由用例锁定，契约与运维手册写明维度必须是正整数。SLICE-209 让触发注册接受注册表输出里的裸 64 hex：`AgentTrigger.digest` 放宽为可带 `sha256:` 前缀，并在模型层统一归一化，其他形状仍然拒绝。SLICE-210 把 `BudgetTracker` 接进 `serve-model-gateway`：注册表解析出的 `budget_usd` 现在真的执行，超限 403 `model_denied` 并审计 `budget_exceeded`；`build_rag_factory` 可注入共享 tracker，跨副本预算仍未实现。SLICE-211 把重新摄取改成整源替换：新分块写入的同一事务里删除该来源不再存在的分块，文件变短不再留下陈旧尾部分块，其他来源不受影响。SLICE-212 让目录摄取在打开时拒绝被换入的符号链接：POSIX 用 `O_NOFOLLOW`，打开后再用 `fstat`/`lstat` 复核，失败按读取错误退出 1。SLICE-213 把无 OIDC 控制台的租户限制写进运维与使用手册：主体固定 `local`，RAG 与配额只覆盖该租户，正式部署用 OIDC 的 `tenant` claim。SLICE-214 把检索置信度改成截断的余弦相似度（`max(0, min(1, 1 - distance))`），默认 `min_confidence=0.5` 从此真正过滤正交分块；用户批准更新了两处既有断言。SLICE-215 把目录摄取改成逐段 `dir_fd` 打开，父目录被换入符号链接也会被拒绝，路径不在根目录下直接报错。SLICE-216 给验收脚本加 `--smoke`（P1–P4）发布前子集，选择逻辑抽成纯函数并有用例锁定。

## 里程碑

| 里程碑 | 状态 | 出口证据 |
| --- | --- | --- |
| M0 地基 | done | `docs/evidence/M0-milestone.txt` |
| M1 单 agent 闭环 | done | `docs/evidence/M1-milestone.txt` |
| M2 工具与策略 | done | `docs/evidence/M2-milestone.txt` |
| M3 编排 | done | `docs/evidence/M3-milestone.txt` |
| M4 平台加固 | done | `docs/evidence/M4-milestone.txt` |
| M5 拆分 | done | `docs/evidence/M5-milestone.txt` |
| UI（SLICE-036） | done | `docs/evidence/SLICE-036-console-progress.txt` |
| M6 Enterprise Trust Chain | done | `docs/review/m6-enterprise-trust-chain.md` + SLICE-163..177 证据 |

路线图见 `docs/specs/ROADMAP.md`。

## 最近切片与提交

| 切片 | 内容 | 提交 |
| --- | --- | --- |
| SLICE-028 | 租户隔离与配额 | `6c5ea8d` |
| SLICE-029 | RBAC 与策略管理界面 | `0be628b` |
| SLICE-030 | 评测门禁与灰度 | `24198c6` |
| SLICE-031 | A2A 消费方与提供方评估（可选） | `769794f` |
| SLICE-032 | 模型网关独立部署 | `9a7aa53` |
| SLICE-033 | 工具网关独立部署 | `ca7c7eb` |
| SLICE-034 | worker 横向扩容（共享 Postgres 会话） | `07b61e1` |
| SLICE-035 | 审计管线独立部署与租户哈希链 | `3b17b43` |
| SLICE-036 | 控制台 SSE 进度与 trace 视图 | `3fcf12d` |
| SLICE-037 | 审计客户端接入两个网关 | `911654d` |
| SLICE-038 | 只读运营视图（注册表、run、会话、评测） | `3354ebe` |
| SLICE-039 | OIDC 身份解析器核心 | `8673e7c` |
| SLICE-040 | OIDC 控制台接线与租户隔离 | `4842043` |
| SLICE-041 | OIDC 服务面接线与 principal 绑定 | `6c775b2` |
| SLICE-042 | MCP HTTP OIDC 认证 | `6d3bd45` |
| SLICE-043 | MCP principal 注入与会话隔离 | `9568f5c` |
| SLICE-044 | 共享配额（Postgres 运行计数与并发租约） | `091dc4e` |
| SLICE-045 | 审批收件箱与计划可视化（UI-2） | `db1c965` |
| SLICE-046 | MCP 运行路径审计与配额 | `e2834fb` |
| SLICE-047 | 指标与 trace 传播 | `2caa38e` |
| SLICE-048 | A2A 运行路径审计与配额 | `17aec23` |
| SLICE-049 | 审批过期与提交提醒 | `a061a48` |
| SLICE-050 | 服务指标端点（网关与 MCP） | `dc8016e` |
| SLICE-051 | 审批记录归档与删除 | `a6e67e0` |
| SLICE-052 | 配额表行级隔离（Postgres RLS） | `9f25c78` |
| SLICE-053 | 审计轮转与签名 | `ac62f02` |
| SLICE-054 | 模型调用熔断 | `4c576b5` |
| SLICE-055 | 文件状态备份与恢复 | `08b157a` |
| SLICE-056 | 压测基线（配额并发与审计吞吐） | `60a5acb` |
| SLICE-057 | SSE 慢客户端与有界进度队列 | `6f3a0bb` |
| SLICE-058 | 入口限流（控制台与三个服务） | `12e402b` |
| SLICE-059 | MCP 与 A2A 入口限流 | `4eddd72` |
| SLICE-060 | 审计签名密钥轮换（`kid` 与密钥环） | `4d268c8` |
| SLICE-061 | 会话按租户隔离（可选开关） | `44abd21` |
| SLICE-062 | 审计只读查询 API | `68afdf9` |
| SLICE-063 | 控制台接共享审计 | `59b58c5` |
| SLICE-064 | 工件类型与端口（ADR-0008） | `00b504d` |
| SLICE-065 | 工件存储（文件与 Postgres） | `b3a4c25` |
| SLICE-066 | 发布带工件与签名 | `577e6ec` |
| SLICE-067 | 工件加载与验签 | `4427764` |
| SLICE-068 | 从注册表启动（控制台与 MCP） | `3938322` |
| SLICE-069 | 市场视图与工件状态（UI-3） | `1b3b5d5` |
| SLICE-070 | Postgres 注册表 | `a04828b` |
| SLICE-071 | 注册表控制面与客户端 | `325078e` |
| SLICE-072 | 命令接注册表服务 | `6d88dcc` |
| SLICE-073 | 市场页按需加载版本 | `3f0c495` |
| SLICE-074 | 评测报告集中存储 | `fdcf6c8` |
| SLICE-075 | 只读工具目录（UI-4） | `98d0544` |
| SLICE-076 | 生命周期存储与接口 | `4931e0e` |
| SLICE-077 | 生命周期拦截与控制台 | `515d7e1` |
| SLICE-078 | 工具授权请求存储 | `c1c5d4f` |
| SLICE-079 | MCP 与 A2A 工具授权 | `a6ce1cb` |
| SLICE-080 | 临时授权运行时合并 | `f19bdb7` |
| SLICE-081 | 工具授权申请与审批 | `8a578de` |
| SLICE-082 | 工具授权使用统计与到期提示 | `5b8bc93` |
| SLICE-083 | 市场页卸载与置换 | `0983ea0` |
| SLICE-084 | 跨副本限流 | `dd2de07` |
| SLICE-085 | 连接器类型与存储 | `120a711` |
| SLICE-086 | 连接器执行适配器 | `5e48150` |
| SLICE-087 | 连接器控制面与控制台 | `b9d5a20` |
| SLICE-088 | 连接器并入工具目录 | `50f3684` |
| SLICE-089 | 连接器健康检查 | `c1c8bd2` |
| SLICE-090 | A2A peer 身份与授权 | `57d5ebc` |
| SLICE-091 | peer 管理面 | `49d802c` |
| SLICE-092 | 模式互斥验证与迁移 | `b29ce75` |
| SLICE-093 | 远端 agent 目录记录 | `5156219` |
| SLICE-094 | 市场页合并远端条目 | `e0ea89f` |
| SLICE-095 | A2A 出站审计 | `b6c0d10` |
| SLICE-096 | 审计 Postgres 写读验链 | `069529a` |
| SLICE-097 | 审计数据库接线 | `8cf8f27` |
| SLICE-098 | 审批的 Postgres 收件箱 | `f05d8ee` |
| SLICE-099 | 审批数据库接线 | `8e20a2b` |
| SLICE-100 | 多副本清单与运维手册 | `da6f9d3` |
| SLICE-101 | 发行完整性 | `3a7dcc4` |
| SLICE-102 | 构建供应链收尾 | `1334fea` |
| SLICE-103 | 会话存储租户 RLS | `4f66e4d` |
| SLICE-104 | 会话 RLS 运维收口 | `f12246e` |
| SLICE-105 | 应用级状态租户 RLS | `f6863ca` |
| SLICE-106 | 应用级状态 RLS 运维收口 | `358c12c` |
| SLICE-107 | 密钥扫描加固与风险到期 | `6462a6d` |
| SLICE-108 | 密钥基线只读 | `9510594` |
| SLICE-109 | 发布流水线与 digest 回写 | `abc881b` |
| SLICE-110 | OTel 导出与 trace 瀑布 | `8f3846c` |
| SLICE-111 | 运行检查点与恢复 | `a70088d` |
| SLICE-112 | 输入输出护栏 | `0459b82` |
| SLICE-113 | 控制台 OIDC 登录与应用外壳 | `5cffc0a` |
| SLICE-114 | 运行详情瀑布 | `75e0b15` |
| SLICE-115 | 审批工作台 | `69531f9` |
| SLICE-116 | 市场卡片改版 | `25ac1aa` |
| SLICE-117 | 角色视图与能力清单 | `e2fce48` |
| SLICE-118 | 审批历史 | `d46c32b` |
| SLICE-119 | 运行详情下钻 | `eeb4af1` |
| SLICE-120 | 日志注入过滤 | `2832776` |
| SLICE-121 | 租户凭据引用绑定 | `666249b` |
| SLICE-122 | 连接器自助申请与审批 | `7dfc8f5` |
| SLICE-123 | 声明式组合器 | `aad70bf` |
| SLICE-124 | 触发定义与存储 | `dea13e3` |
| SLICE-125 | webhook 触发执行服务 | `36b9810` |
| SLICE-126 | 文件存储路径加固 | `e6e4819` |
| SLICE-127 | 调度循环与重试 | `66843e6` |
| SLICE-128 | 执行层级进入 manifest | `c75142e` |
| SLICE-129 | agent 子进程沙箱 worker | `744846c` |
| SLICE-130 | 模型出口中介 | `5492dae` |
| SLICE-131 | 触发路径接入沙箱 | `b23fb2a` |
| SLICE-132 | 审批接口能力校验 | `9642889` |
| SLICE-133 | 控制台读接口能力校验 | `62497aa` |
| SLICE-134 | 控制台与 MCP 沙箱执行适配 | `eb757d9` |
| SLICE-135 | A2A 的注册表启动 | `8f35fcb` |
| SLICE-136 | 沙箱工具调用中介协议 | `fc3ae87` |
| SLICE-137 | 工具执行器接入工具网关 | `1409e80` |
| SLICE-138 | 构建密钥 | `f60764d` |
| SLICE-139 | 凭据信封加密 | `1eab441` |
| SLICE-140 | 凭据运行时接入 | `b396c68` |
| SLICE-141 | `remote-agents` 凭据接入 | `23bf04d` |
| SLICE-142 | 控制面凭据写入端点 | `fa56229` |
| SLICE-143 | 数据密钥重包裹与 rewrap | `844fd89` |
| SLICE-144 | 安装与使用手册 | `dadd75c` |
| SLICE-145 | v0.1.0 发布说明 | `2406b9a` |
| SLICE-146 | spec 用例名校验与切片清单 | `e8ffd7e` |
| SLICE-147 | 用例引用识别与沙箱契约修正 | `d9f0f63` |
| SLICE-148 | AD/Entra/ADFS OIDC 指南 | `684caf6` |
| SLICE-149 | 本地 KEK 只读 keyring 与权限检查 | `c9f1147` |
| SLICE-150 | 解密失败审计与 keyring 边界 | `44a5396` |
| SLICE-151 | 解密失败审计的边界收口 | `56d2045` |
| SLICE-152 | 凭据审计版本号共享与安全化 | `672caab` |
| SLICE-153 | 控制台写路径与基础接口能力校验 | `751fbfc` |
| SLICE-154 | 工件内 manifest 与发布记录绑定 | `e5c2980` |
| SLICE-155 | 凭据配置错误统一退出 | `6bdc3f6` |
| SLICE-156 | 控制台凭据登记拒绝请求体密文 | `5a13292` |
| SLICE-157 | 凭据存储读取与加锁健壮性 | `363e0de` |
| SLICE-158 | 控制台凭据列表的非法租户参数 | `af3cc60` |
| SLICE-159 | 工具授权决定收紧到 admin | `94e9855` |
| SLICE-160 | Vault/OpenBao Transit 密钥后端 | `37520fc` |
| SLICE-161 | Vault 安装与运维文档 | `3979a7d` |
| SLICE-162 | 本地 KEK 到 Vault 的凭据迁移 | `71b98a5` |

每个切片的详细验收、反例和威胁建模在 `docs/specs/SLICE-0xx-*.md`，证据在 `docs/evidence/`。

## 当前验证状态

本机（装了可选驱动）:

- `./.venv/Scripts/python.exe scripts/check.py --full` -> 9 步全 PASS，1890 passed, 98 skipped（`docs/evidence/SLICE-203-audit-chain-docs.txt`）
- 设置 `TEST_POSTGRES_URL` 后 Postgres 用例可跑；完整套件的旧记录为 1236 passed, 1 skipped（`docs/evidence/SLICE-105-app-state-rls.txt`）。
- CI 在 PR #65 上全绿（gate、analyze、CodeQL），包含锁安装、`--no-build-isolation`、完整门禁、镜像构建、Trivy 扫描与 SBOM 上传。系统 `python` 缺项目依赖，必须用 venv 里的解释器。

跳过项主要是需要 `TEST_POSTGRES_URL` 的 Postgres 集成用例（配额、RLS、注册表、peer、远端目录、审计），以及 `RLIMIT_AS` 仅 POSIX 的平台跳过。设 `TEST_POSTGRES_URL` 后本地全部可跑。CI 不装 `a2a-sdk`，另有少量 A2A 用例按条件跳过。

## 怎么跑

下面的 Postgres DSN 不写口令。本地用 `PGPASSWORD` 或 `~/.pgpass` 提供，不要把明文写进命令或文档。

```bash
# 唯一门禁
python scripts/check.py --fast
python scripts/check.py --full

# 控制台（本地开发）
python -m adk_agent console --agents examples/minimal/agent.py \
  --host 127.0.0.1 --port 8081 --allow-unauthenticated

# 控制台带共享配额（多副本时 QUOTA_URL 指向同一个库）
QUOTA_URL=postgresql://postgres@127.0.0.1:5432/adk \
  python -m adk_agent console --agents examples/minimal/agent.py \
  --quota-config quota.json

# 控制台带审批收件箱，执行器和控制台共用同一个目录
python -m adk_agent console --agents examples/minimal/agent.py \
  --approval-dir ./approvals --approval-ttl 3600

# MCP 服务带审计、配额和指标
QUOTA_URL=postgresql://postgres@127.0.0.1:5432/adk \
  python -m adk_agent serve --agent examples/minimal/agent.py \
  --transport streamable-http --audit-file ./audit.jsonl \
  --quota-config quota.json --metrics

# 工具网关和模型网关默认暴露 /metrics（需要 token）
curl -H "Authorization: Bearer $ADK_MCP_AUTH_TOKEN" http://127.0.0.1:8000/metrics

# 归档 60 秒前终结的审批记录（默认移到 <dir>/archive）
adk-agent approvals prune --dir ./approvals --older-than 60

# 会话按租户隔离（会让旧会话不可见，按部署决定开启）
adk-agent console --agents agents.py --session-tenant-scope
adk-agent serve --agent agent.py --transport streamable-http --oidc-config oidc.json \n  --session-tenant-scope

# 一键生成演示状态：两个已签名 agent、评测报告、待审请求、截图用控制台命令
python scripts/demo_seed.py --root demo
cat demo/keys.json   # 填入 ADK_ARTIFACT_KEYS 后启动控制台

# 从注册表直接启动（控制台或 MCP），用发布的工件而不是本地 agent.py
ADK_ARTIFACT_KEYS='{"publisher-1":"<64 hex public key>"}' \n  adk-agent console --agent-ref acme/bot@1.0.0 \n  --registry ./registry --artifact-dir ./store

# 发布带工件（目录或 zip），Ed25519 签名，字节入文件 store 或 ARTIFACT_URL
ARTIFACT_URL=postgresql://postgres@127.0.0.1:5432/adk \n  adk-agent publish manifest.json --artifact ./my-agent \n  --key publisher.pem --key-id publisher-1

# 控制台读写共享审计服务（审计、运行、trace 面板都读服务）
ADK_AUDIT_AUTH_TOKEN=... adk-agent console --agents agents.py \n  --audit-url http://127.0.0.1:8000 --audit-token-env ADK_AUDIT_AUTH_TOKEN

# 审计只读查询（需要审计服务 token）
curl -H "Authorization: Bearer $ADK_AUDIT_AUTH_TOKEN" \n  'http://127.0.0.1:8000/v1/events?tenant=acme&limit=50&order=desc'

# 审计密钥环：轮换后旧记录仍可验证（legacy 指向无 kid 的历史密钥）
ADK_AUDIT_KEYRING='{"active":"k2","keys":{"k1":"...","k2":"..."},"legacy":"k1"}' \n  adk-agent serve-audit --out ./audit.jsonl

# 审计服务：每 1000 条轮转一段，用环境变量里的密钥签名
ADK_AUDIT_SIGNING_KEY=... adk-agent serve-audit --out ./audit.jsonl \
  --audit-max-records 1000
ADK_AUDIT_SIGNING_KEY=... adk-agent verify-audit ./audit.jsonl

# 模型网关：连续 5 次 provider 失败后熔断 30 秒
adk-agent serve-model-gateway --provider litellm \
  --breaker-failures 5 --breaker-reset 30

# 控制台指标（需要同一个 bearer token）
curl -H "Authorization: Bearer $ADK_MCP_AUTH_TOKEN" http://127.0.0.1:8081/metrics

# A2A 服务带审计和配额（需要可选依赖 a2a-sdk）
python -m adk_agent serve-a2a --agent examples/minimal/agent.py \
  --audit-file ./audit.jsonl --quota-config quota.json

# 配额并发与审计吞吐基线（Postgres 用 --url 或 LOADTEST_URL）
python scripts/loadtest.py quota --requests 2000 --concurrency 32 --max-runs 1000 \n  --url postgresql://postgres@127.0.0.1:55432/adk
python scripts/loadtest.py audit --records 5000 --path ./audit-bench.jsonl --max-records 1000

# MCP 与 A2A 也支持限流（MCP 限 streamable-http）
adk-agent serve --agent agent.py --transport streamable-http \n  --rate-limit 120 --rate-limit-window 60

# 入口限流：每个调用方每 60 秒 120 次（/healthz 与 /metrics 豁免）
adk-agent serve-tool-gateway --tools tools.py --rate-limit 120 --rate-limit-window 60

# SSE 慢客户端场景：突发多少条、缓冲多大、客户端每条多久
python scripts/loadtest.py sse --events 10000 --queue-size 256 --consumer-delay-ms 1

# 备份注册表、审批和审计（审计段一起打包），再恢复到空目录
adk-agent backup --out ./backup.tar.gz --registry ./registry \
  --approvals ./approvals --audit ./audit.jsonl
adk-agent restore --archive ./backup.tar.gz --dest ./restored
```

模型通道用 `ADK_AGENT_MODEL`，例如 `claude:deepseek-v4-pro`。

独立服务：

- `adk-agent serve-model-gateway`
- `adk-agent serve-tool-gateway --tools FILE`
- `adk-agent serve-audit --out FILE` 和 `adk-agent verify-audit FILE`
- `adk-agent serve-a2a`（需要可选依赖）

## 未决事项（恢复时先看）

1. ADR-0001 到 ADR-0027 均已接受。ADR-0003 到 ADR-0006 决定可选依赖不进默认依赖，ADR-0007 新增可选 extra `oidc`（`PyJWT[crypto]`），ADR-0019 决定会话表用 Postgres RLS 做租户隔离，ADR-0020 把 `app_states` 纳入同一边界，ADR-0021 决定 OTel 导出边界，ADR-0022 决定能力驱动的角色视图、声明式组合、自动化与 agent 沙箱顺序，ADR-0023 决定 CodeQL 安全审核通道，ADR-0024 决定 agent 级沙箱的进程隔离、资源上限与出口中介，ADR-0025 决定凭据信封加密与密钥后端端口，ADR-0026 决定密钥后端选型框架与本地 KEK 过渡方案，ADR-0027 选定 Vault/OpenBao Transit 后端与 `v: 2` payload。
2. 本地 venv 为验证装了 `a2a-sdk`、`sqlalchemy`、`asyncpg`、`greenlet`，都不在项目依赖里。换环境要先装。
3. 未跟踪的 `.agents/`、`.claude/agents/`、`.claude/skills/`、`package.json`、`package-lock.json` 是本地工具，不要加进仓库。

## 已知缺口与下一刀建议

已核实的开放项：

1. 首次真实发布已完成（v0.1.0，tag 指向 `2406b9a`，release notes 见 `docs/releases/v0.1.0.md`，本地镜像 smoke 通过）。后续发布仍由操作员手动触发 release workflow：设置 registry 凭据、在 `master` 上触发，再把 digest 回写 PR。见 `docs/evidence/SLICE-109-release-pipeline.txt`。
2. 密钥扫描不做历史扫描（gitleaks/trufflehog 延后）。GitHub 自定义 pattern 与 validity checks 需要付费套餐，当前关闭。
3. legacy 无前缀 `user_id` 与 plain `app_name` 在 `--session-rls` 开启后不可见，不自动迁移；需要迁移时单独评审。
4. UI 侧的登录、应用外壳、运行详情瀑布、审批工作台、市场卡片、角色视图、审批历史与运行详情下钻已完成，日志注入过滤、租户凭据引用绑定、连接器自助申请、声明式组合器、触发定义、webhook 执行、路径加固、调度循环、执行层级、agent 沙箱 worker、模型出口中介、触发路径的沙箱接入、审批接口、控制台读接口的能力校验与控制台/MCP 的沙箱执行适配、A2A 的注册表启动、沙箱工具调用中介协议、工具执行器接入、构建密钥、凭据信封加密与运行时接入、`remote-agents` 的凭据接入、控制面凭据写入端点、数据密钥重包裹、安装与使用手册、spec 用例名校验、AD/Entra/ADFS OIDC 指南、本地 KEK 加固与解密失败审计也已收口（SLICE-113 到 152）。v0.1.0 已于 2026-11-18 发布。SLICE-110 到 SLICE-152 已完成。
5. 租户凭据只存引用，不存值。密钥后端已由 SLICE-139 交付（本地 KEK 信封加密），运行时解析已由 SLICE-140/141 接入工具网关、控制台与 `remote-agents`，控制面写入端点由 SLICE-142 交付，数据密钥重包裹（`credentials rewrap`）由 SLICE-143 交付；本地 KEK 只读 keyring 与权限检查由 SLICE-149 交付，解密失败审计由 SLICE-150 到 152 交付；凭据密钥后端已由 ADR-0027 选定 Vault/OpenBao Transit，`VaultKeyBackend` 与 `v: 2` payload 由 SLICE-160 交付，安装与运维手册由 SLICE-161 交付，迁移命令由 SLICE-162 交付；PKCS#11/HSM、KMIP 与云 KMS 未实现；工具网关只做租户作用域，绑定存在性在连接器登记处检查。连接器申请没有过期、通知与控制面接口。组合器只有 `single-llm` 一个模板；控制台发布表单由 SLICE-280/281 交付（仅该模板），模型通道固定为 LiteLLM allowlist。触发执行已覆盖 webhook 与 schedule，调度按 slot 单赢家且只跑当前 slot，agent 失败不自动重试。文件存储路径已统一走 `safe_join`，Postgres 后端不受影响。执行层级已进 manifest：新发布必须显式声明，无沙箱后端时 `sandboxed` 在发布与加载两处被拒；历史记录缺字段按 `in_process` 读取且 digest 不变。组合器与脚手架当前明确写 `in_process`，手写 manifest 暂无法与平台产物区分；SLICE-129 已交付子进程 worker 与协议，但尚未注册后端，publish 仍默认不可用；接入切片把 publish 默认翻成 `sandboxed`，`in_process` 只接受平台构建密钥签名的工件。沙箱 worker 的残余风险：POSIX 上 RLIMIT_NPROC 按 uid 计数且默认关闭，工件仍可读宿主文件系统，Windows 只有脚本级守卫；网络守卫是 Python 层，内省拿原始 C 类型或用 ctypes 可绕过。模型调用与工具调用都已经父进程中转，工具调用经工具网关（SLICE-137）；沙箱发布还必须同时落地平台门槛（POSIX、降 uid、网络命名空间）、`sandboxed` 的执行路由与平台构建密钥校验，再允许注册后端。这些按 ADR-0022 与 ADR-0024 的顺序另行切片。

6. 控制台的读路径已在 SLICE-133 对齐到面板能力（审计、策略、注册表与评测、工具、工具授权、连接器与申请、凭据、对端与远程目录）。SLICE-153 补上写路径与基础接口：注册表 load/unload 检查 `registry.load`，tool-grants 提交检查 `grants.request`，`/api/runs`、`/api/plans`、`/api/traces/{id}`、`/api/sessions`、`/api/chat` 检查基础能力（基础能力对现有每个角色都为真，租户隔离仍由既有过滤保证）。其余写接口维持 admin 判断，与只有 admin 才有的 `connectors.manage`/`peers.manage` 等价。`grants.decide` 的界面服务端不一致已由 SLICE-159 收口：operator/ops/approver 不再映射该能力，界面按钮隐藏，服务端保持 admin-only（会话确认，收紧而非放宽）。审批历史查询参数 `limit` 由 FastAPI 在进入处理函数前转换，越权调用方带非整数 `limit` 会先得 422 而非 403；不泄露数据，记为已知小缺口。SLICE-233（`93af8d8`）把读/写路由的能力检查统一移到 principal 解析后第一条语句（先于 config 404、非法参数 400 与租户检查），关闭「未授权调用方探测配置存在性」侧信道；写路径的 admin 判定改为 `connectors.manage`/`peers.manage`/`grants.decide` 能力（行为不变，与前端 `data-capability` 一致）。SLICE-234（`e652a7a`）把导入路由也收口：`POST /api/import/agent` 挂 `registry.publish`（publisher+admin），`POST /api/import/terminology` 挂新的 `semantics.write`（admin+operator），都是 principal 解析后第一条语句。SLICE-235（`8dfec14`）把只读面板收为 operator+：新增 `ops.read`（admin+operator）门控 overview/quota/rag/semantics，model 面板复用 `model.read`；服务端五个端点加检查，前端 tab/section 改 `data-capability` 并在 connect/SSE tick 按能力跳过加载。剩余待拍板：ask-ai 与 import 面板仍 `runs.read` 基础可见；「业务用户逐条写术语表」的轻量入口需新端点；租户切换监听里 `loadOverview()` 未按 `ops.read` 守卫（非安全，多余一次 403，可后续顺手收）。
7. SLICE-138 的构建签名只绑定工件 digest，不绑定发布记录 manifest。SLICE-154 在控制面补上比较：上传时要求工件内 manifest 与所有租户中引用该 digest 的记录 manifest 一致，发布时在字节已存在的情况下再查一次；CLI 端原本就比较。残余：签名本身仍不覆盖 manifest（需要新签名格式，另行评审）；任一租户发布不匹配记录会让该 digest 的上传 fail-closed，且没有删除记录接口，只能换新工件。`scripts/demo_seed.py` 属本地演示信任域，仍生成只带演示发布签名、没有平台构建签名的 `in_process` 工件。
8. SLICE-140 的残余：SLICE-155 已让 `serve-tool-gateway` 无条件校验凭据参数（只给 `--tools` 时给凭据参数退出 1），`--credential-db` 与 `CREDENTIAL_DATABASE_URL` 同时给出退出 2，工具网关、`remote-agents` 与控制台在 keyring 非法时退出 1。`remote-agents` 的测试已清空 `CREDENTIAL_DATABASE_URL`，工具网关与控制台远程 agent 的两个接线用例仍未清空。ADR-0025 第 8 条的 `credential.decrypt_failed` 审计已由 SLICE-150 到 152 交付（失败与缺后端两条路径，元数据写不改 fail-closed；成功解析仍不逐次审计，这是 ADR-0025 的既定取舍）。`ADK_SECRET_KEKS` 格式非法时 `serve-registry` 已给提示退出 1；SLICE-155 之后工具网关、`remote-agents` 与控制台也退出 1。SLICE-142 的残余：控制台 `/api/credentials` 的请求体密文已由 SLICE-156 拒绝；admin 跨租户写入的审计落在调用方租户链；Postgres 下并发停用可能重复写 `credential.disable`；凭据池关闭 best-effort。超过 128 字符的 `credential_id`/`tenant` 已由 SLICE-143 的长度上限改为 400。SLICE-143 的残余：Windows 文件锁的重试已由 SLICE-157 限次（约 5 秒）并转为存储错误；旧记录（id > 128）读取时抛存储错误（控制台 503、CLI 退出 1），不再 500；控制台凭据列表的非法 `tenant` 参数已由 SLICE-158 改为 400 `unsafe_tenant`；超长 `credential_id` 路径仍可能抛 `UnsafePath`；只读目录上停用已停用的记录会因建锁文件失败；CLI 的 rewrap 在锁外计算新 payload（`replace_wrapped` 会重读合并，两个不同 keyring 的并发 rewrap 由最后写入者胜出）。SLICE-149 到 152 的残余：Windows 不做 keyring ACL 检查（只跳过，不伪造检查）；工具网关、`remote-agents` 与控制台的 keyring 非法已由 SLICE-155 改为退出 1；控制台 `/api/credentials` 请求体密文已由 SLICE-156 拒绝；跨租户 admin 写入的审计落在调用方租户链；Postgres 并发停用可能重复写 `credential.disable`；凭据池关闭 best-effort；解密失败审计在工具网关和控制台没有 invocation，主体是服务主体；超过 128 字符的旧凭据记录读取时 fail-closed（SLICE-157），需要手工清理。

9. RAG 残余：摄取（单文件/stdin/目录）与检索可从 CLI 用，运行时预取、注入边界、`rag.retrieve` 审计与控制台/触发接线已由 SLICE-197 到 199 交付（ADR-0036 slice 2-4）；MCP 与 A2A 入口已由 SLICE-206 接线；沙箱化触发已由 SLICE-207 接上检索（预取在配额预留后、沙箱运行前，失败映射 `rag_unavailable`）；模型网关已由 SLICE-210 接上进程内 `BudgetTracker`（`budget_usd` 现在真的执行，超限 `budget_exceeded`），`build_rag_factory` 可注入共享 tracker；跨副本预算与控制台 `GatewayLlm` 的 manifest 预算仍未执行；`--rag-dimensions` 必须是正整数，0 或负数在服务启动时退出 1（SLICE-208）；`RagFactory` 的 `policy` 参数可覆盖 manifest 策略（当前 CLI 不传，生产按 manifest 生效，契约已注明）；`--budget-usd` 仍是进程内语义；pgvector SQL 已在 `prove_it_works.py` 的 live 容器里验证（扩展 0.8.7、建表、ACL 检索），真实 LiteLLM embedding 仍未验证；检索没有重排与引用拼接；置信度已由 SLICE-214 改为截断到 `[0, 1]` 的余弦相似度，默认 `min_confidence=0.5` 真正过滤正交分块（用户批准改判据，运维手册与契约已同步）；目录摄取不做增量同步；同一来源重新摄取已由 SLICE-211 改为整源替换；列目录后被换入的符号链接已由 SLICE-212 在 POSIX 上拒绝（`O_NOFOLLOW` 加打开后的 `fstat`/`lstat`），父目录被换入也由 SLICE-215 用逐段 `dir_fd` 打开补上；Windows 仍无 `O_NOFOLLOW`，只做打开后的 `fstat`/`lstat` 复核；注入中和只剔除 Unicode `Cf` 类字符，`Mn` 类不可见字符仍可穿过标签词；运维与使用手册已由 SLICE-200 补齐。审计链的哈希口径与运维说明已由 ADR-0037 / SLICE-201 到 203 收口：校验按存储内容重算，历史里存储内容已与 `hash` 对不上的记录（如 `-0.0` 写入后被存成 `0.0` 的行）不自动迁移，继续按断链调查。

10. 2026-11-21 端到端验收（`docs/reviews/retrospective-2026-11-21.md`、`docs/evidence/prove-2026-11-21.txt`）确认的缺口，按风险排序：
    - ~~console 启动引用（`--agent-ref`）加载的 agent 不构造 `RagContext`~~ 已由 SLICE-204 修复；按需加载路径本来就正常。
    - ~~`model_allowlist` 目前哪里都不执行~~ 已由 SLICE-205 执行（直连、别名与 `GatewayLlm`），ADR-0033 补落地记录。
    - ~~`triggers register --digest` 要求 `sha256:` 前缀，注册表记录是裸 hex~~ 已由 SLICE-209 修复：裸 64 hex 也可注册，存储统一归一化为 `sha256:<hex>`。
    - ~~无 OIDC 的 console 主体租户固定为 `local`，RAG 只能看到该租户文档；正式部署需 OIDC claim 提供租户~~ 已由 SLICE-213 写进运维与使用手册：该模式只覆盖 `local`（admin 读路径仍可见其它租户审计），正式部署用 OIDC 的 `tenant` claim。
    - 验收脚本依赖 `[litellm]` extra 与可用的 pgvector 镜像源；按未锁定版本安装会引入带已知漏洞的 `wcmatch`，验收后应恢复依赖。

11. ADR-0038（语义层）2026-11-22 已确认，MVP 连续执行中（`docs/decisions/ADR-0038-semantic-layer.md`）：
    - SLICE-217 语义层核心数据模型：术语层（Concept/Term/Mapping）与能力层（CapabilityId）的类型与契约，校验标签唯一、层级无环、`exact_match` 一致。~~已合并 `e8cf480`~~
    - SLICE-218 术语层存储：registry 双后端（文件 + Postgres），租户隔离，复用 `safe_join` / RLS。~~已合并 `ba2361a`~~
    - SLICE-219 数据领域维：领域概念类型，与敏感度 `DataClass` 正交，租户可扩展。~~已合并 `a14c331`~~
    - SLICE-220 能力映射：能力 id 关联 `tool_grants` / A2A skill，校验能力 id 不悬空。~~已合并 `4daa518`~~
    - SLICE-221 确定性语义路由：需求 → 概念 → 能力 → agent 的确定性映射，落到 `PlanStrategy`。~~已合并 `9048c8c`~~
    第二阶段（语义路由模型化、独立图存储、标注验收）按 ADR 触发条件另行分配。

12. ADR-0039（控制台全平台能力总览与 Ask AI 入口）2026-11-22 已确认，MVP 连续执行中（`docs/decisions/ADR-0039-console-capability-overview.md`）：
    - SLICE-222 UI 视觉基线：侧边栏 + 卡片系统 + 浅色优先主题，升级现有 12 面板骨架，不新增功能。~~已合并 `7e87006`~~
    - SLICE-223 总览首页：聚合卡片网格，深链到各面板。~~已合并 `8ad77bc`~~
    - SLICE-224 审计面板 + 配额面板：只读查询可视化。~~已合并 `f58ec0e`~~
    - SLICE-225 RAG 面板 + 模型网关面板：只读查询可视化。~~已合并 `550872c`~~
    - SLICE-226 语义层面板：术语表、概念、能力绑定、路由回放。~~已合并 `ce0c554`~~
    - SLICE-227 通用导入：术语表 / agent 定义 / RAG 语料三类格式。~~已合并 `2bc1fa2`~~
    - SLICE-228 全局 Ask AI：确定性语义路由展示 + 深链。~~已合并 `d1fbe5f`~~
    第二阶段（Ask AI 完整编排、前端框架、可视化实时化）按 ADR 触发条件另行分配。

13. filelock 13 个 CVE（CVE-2026-112907 到 112940）复审结论（2026-11-22）：根因是项目 pin
    `litellm<1.106.3`（ADK 为规避 1.107.0 供应链投毒而设的上限，ADK 2.15.0 仍 cap），该上限要求
    `filelock<4.0`；修复版 filelock 4.2.1 只在 litellm>=1.109.2 可用，故无法在不覆盖 pin 的前提下升级。
    `.trivyignore.yaml` 的 statement 已按此更新，过期日 2027-05-01。触发条件：ADK 放宽 litellm 上限后
    升级 litellm → 顺带升 filelock 4.2.1，移除这 13 条 ignore。应用不直接调用 filelock，CVE 为本地
    攻击向量（AV:L），风险有限。

14. ADR-0040（全局默认模型配置与动态切换）2026-11-22 已确认，MVP 已关闭（`docs/decisions/ADR-0040-global-default-model.md`），
    另加 UI 实时刷新（ADR-0039 第二阶段候选 3，触发条件已确认，用 SSE，FastAPI 内置无需新依赖）：
    - SLICE-229 UI 实时刷新：总览与各能力面板的指标经 SSE 推送，自动更新。~~已合并 `c469261`~~
    - SLICE-230 模型配置类型与 store：`ModelConfigStore` 协议 + 文件/Postgres 双实现，`set_default_model` /
      `_default_model_config` 读 override，优先级落地。~~已合并 `fe11471`~~
    - SLICE-231 控制台端点 + 管理员 UI：`GET/PUT /api/model-config`（`model.read` admin+operator、写 admin-only），
      模型面板加「设置默认模型」，写审计 `model.configure`。~~已合并 `d23186e`~~
    - SLICE-232 验收：`prove_it_works` 断言改配置后新 chat 用新模型，pytest 覆盖优先级与权限。~~已合并 `10d44c1`~~

15. ADR-0041（控制台产品化 UI + Vue 前端）2026-11-23 已确认 Accepted（`docs/decisions/ADR-0041-console-vue-productization.md`），
    技术栈 Vue 3 + Vite + Vue Router 4 + Pinia + TypeScript，SPA 分离、FastAPI `StaticFiles` 挂载、后端 `/api/*` 与鉴权不变、
    新旧渲染并行迁移。五阶段 + 阶段 0：
    - **阶段 0**：Vue 地基 + 平价迁移。SLICE-236（脚手架 + FastAPI 挂载）~~已合并 `837696c`~~：新增 `web/`（Vue 3 +
      Vite + TS，`web/dist/` 随仓库提交，免运行时构建），`console --ui {legacy,vue}`（默认 `legacy`），`vue` 时 `/` 与
      `/auth/callback` 返回 `dist/index.html`、`/assets` 挂载静态产物，`/assets/*` 作为鉴权公开前缀（`open_prefixes`）。
      `npm run build` 成功，全量门禁 9 步全 PASS、2008 passed / 103 skipped。证据 `docs/evidence/SLICE-236-vue-scaffold.txt`。
    - SLICE-237（路由 + Pinia + SPA 鉴权流）~~已合并 `992c63c`~~：加 `vue-router`（^4）与 `pinia`（^3），
      `web/src/router/index.ts` 用 `createWebHashHistory` 定义 `/` + 面板占位路由，`web/src/stores/auth.ts` 复刻 legacy
      PKCE 流（token 存 `sessionStorage["adk_token"]`，`/auth/config` + `/auth/token` + `/api/me`），`web/src/api/client.ts`
      加 `Authorization: Bearer`、401 清 token，`main.ts` 安装 pinia+router，`App.vue` 用 `<RouterView>` + 登录屏。后端无改动。
      全量门禁 9 步全 PASS、2013 passed / 103 skipped。证据 `docs/evidence/SLICE-237-router-pinia-auth.txt`。
    - SLICE-238（迁总览面板）~~已合并 `d4c1727`~~：`web/src/views/OverviewView.vue` 按 `ops.read` 拉取 `GET /api/overview`
      渲染 4 张计数卡片（`null` 显示「未配置」），卡片点击按 `panel` 映射到路由；`/` 改用 `OverviewView`，补 `/approvals`、
      `/grants` 占位路由。后端无改动。全量门禁 9 步全 PASS、2016 passed / 103 skipped。证据 `docs/evidence/SLICE-238-overview-vue.txt`。
    - SLICE-239（迁注册表面板）~~已合并 `0f3b57b`~~：`web/src/views/RegistryView.vue` 按 `registry.read` 拉取 `GET /api/registry`
      渲染卡片列表（id/版本/描述 + 徽标 + 元信息），徽标色调复刻 legacy `BADGE_TONES`；`/registry` 改用 `RegistryView`。
      后端无改动。全量门禁 9 步全 PASS、2019 passed / 103 skipped。证据 `docs/evidence/SLICE-239-registry-vue.txt`。
    - SLICE-240（迁工具目录面板）~~已合并 `772a5d6`~~：`web/src/views/ToolsView.vue` 按 `tools.read` 拉取 `GET /api/tools`
      渲染表格（工具 ID/来源/数据分级/需审批/授权 Agent），`/tools` 改用 `ToolsView`。后端无改动。
      全量门禁 9 步全 PASS、2022 passed / 103 skipped。证据 `docs/evidence/SLICE-240-tools-vue.txt`。
    - SLICE-241（迁工具授权面板）~~已合并 `39ddd5c`~~：`web/src/views/GrantsView.vue` 按 `grants.read` 拉取 `GET /api/tool-grants`
      渲染表格（工具 ID/Agent/版本/状态 + 24h 内到期 expiring 徽标/到期时间），`/grants` 改用 `GrantsView`。后端无改动。
      全量门禁 9 步全 PASS、2025 passed / 103 skipped。证据 `docs/evidence/SLICE-241-grants-vue.txt`。
    - SLICE-242（迁审批面板）~~已合并 `146716f`~~：`web/src/views/ApprovalsView.vue` 按 `approvals.read` 拉取 `GET /api/approvals`
      渲染表格（请求 ID 截 16 位/步骤/Agent/理由/提交时间/到期 + soon 徽标），`/approvals` 改用 `ApprovalsView`。后端无改动。
      全量门禁 9 步全 PASS、2028 passed / 103 skipped。证据 `docs/evidence/SLICE-242-approvals-vue.txt`。
    - SLICE-243（迁审计面板）~~已合并 `015e190`~~：`web/src/views/AuditView.vue` 按 `audit.read` 拉取 `GET /api/audit?limit=100`
      渲染倒序等宽日志行（动作/目标/状态/延迟/run/trace），`/audit` 改用 `AuditView`。后端无改动。
      全量门禁 9 步全 PASS、2031 passed / 103 skipped。证据 `docs/evidence/SLICE-243-audit-vue.txt`。
    - SLICE-244（迁模型面板）~~已合并 `08e81f1`~~：`web/src/views/ModelView.vue` 按 `model.read` 拉取 `GET /api/model`
      渲染三张卡片（最近调用/使用别名/降级次数），`/model` 改用 `ModelView`。后端无改动。
      全量门禁 9 步全 PASS、2034 passed / 103 skipped。证据 `docs/evidence/SLICE-244-model-vue.txt`。
    - SLICE-245（迁配额面板）~~已合并 `12e3053`~~：`web/src/views/QuotaView.vue` 按 `ops.read` 拉取 `GET /api/quota`
      渲染五张卡片（窗口运行数/活跃并发/运行上限/并发上限/窗口秒数），新增 `/quota` 路由用 `QuotaView`。后端无改动。
      全量门禁 9 步全 PASS、2037 passed / 103 skipped。证据 `docs/evidence/SLICE-245-quota-vue.txt`。
    - SLICE-246（迁检索面板）~~已合并 `d02055e`~~：`web/src/views/RagView.vue` 按 `ops.read` 拉取 `GET /api/rag`
      渲染三张卡片（最近检索/最近 top_k/最近返回），新增 `/rag` 路由用 `RagView`。后端无改动。
      全量门禁 9 步全 PASS、2040 passed / 103 skipped。证据 `docs/evidence/SLICE-246-rag-vue.txt`。
    - SLICE-247（迁语义层面板）~~已合并 `6e2f0af`~~：`web/src/views/SemanticsView.vue` 按 `ops.read` 拉取 `GET /api/semantics`
      为每个术语表渲染卡片（scheme_id + 概念数），新增 `/semantics` 路由用 `SemanticsView`。后端无改动。
      全量门禁 9 步全 PASS、2043 passed / 103 skipped。证据 `docs/evidence/SLICE-247-semantics-vue.txt`。
    - SLICE-248（迁连接器面板）~~已合并 `b740b14`~~：`web/src/views/ConnectorsView.vue` 按 `connectors.read` 拉取 `GET /api/connectors`
      渲染表格（连接器 ID/租户/类型/Base URL/方法/启用），新增 `/connectors` 路由用 `ConnectorsView`。后端无改动。
      全量门禁 9 步全 PASS、2046 passed / 103 skipped。证据 `docs/evidence/SLICE-248-connectors-vue.txt`。
    - SLICE-249（迁凭据面板）~~已合并 `0455b7b`~~：`web/src/views/CredentialsView.vue` 按 `connectors.read` 拉取 `GET /api/credentials`
      渲染表格（凭据 ID/租户/Secret 引用/描述/启用），新增 `/credentials` 路由用 `CredentialsView`。后端无改动。
      全量门禁 9 步全 PASS、2049 passed / 103 skipped。证据 `docs/evidence/SLICE-249-credentials-vue.txt`。
    - SLICE-250（迁对端面板）~~已合并 `221de71`~~：`web/src/views/PeersView.vue` 按 `peers.read` 拉取 `GET /api/peers`
      渲染表格（对端 ID/租户/主体/类型/启用/授权），新增 `/peers` 路由用 `PeersView`。后端无改动。
      全量门禁 9 步全 PASS、2052 passed / 103 skipped。证据 `docs/evidence/SLICE-250-peers-vue.txt`。
    - SLICE-251（迁运行面板）~~已合并 `83c0bb9`~~：`web/src/views/RunsView.vue` 按 `runs.read` 拉取 `GET /api/runs?limit=50`
      渲染表格（运行 ID 截 12 位/Agent/状态/开始时间/延迟/成本/事件数），新增 `/runs` 路由用 `RunsView`。后端无改动。
      全量门禁 9 步全 PASS、2055 passed / 103 skipped。证据 `docs/evidence/SLICE-251-runs-vue.txt`。
    - SLICE-252（迁会话面板）~~已合并 `ffb6fb5`~~：`web/src/views/SessionsView.vue` 按 `sessions.read` 先拉 `GET /api/agents`
      填选择器再拉 `GET /api/sessions?agent=` 渲染表格（会话 ID/最后更新），新增 `/sessions` 路由用 `SessionsView`。后端无改动。
      全量门禁 9 步全 PASS、2058 passed / 103 skipped。证据 `docs/evidence/SLICE-252-sessions-vue.txt`。
    - SLICE-253（迁计划面板）~~已合并 `5ebd1dd`~~：`web/src/views/PlansView.vue` 按 `runs.read` 拉取 `GET /api/plans?limit=50`
      渲染表格（计划 ID/租户/状态/步骤/审批/开始时间），新增 `/plans` 路由用 `PlansView`。后端无改动。
      全量门禁 9 步全 PASS、2061 passed / 103 skipped。证据 `docs/evidence/SLICE-253-plans-vue.txt`。
    - SLICE-254（迁策略面板）~~已合并 `e721ea3`~~：`web/src/views/PolicyView.vue` 按 `policy.read` 拉取 `GET /api/policy`
      展示策略 JSON（version + bindings），新增 `/policy` 路由用 `PolicyView`。后端无改动。
      全量门禁 9 步全 PASS、2064 passed / 103 skipped。证据 `docs/evidence/SLICE-254-policy-vue.txt`。
    - SLICE-255（迁导入面板）~~已合并 `5eb18f6`~~：`web/src/views/ImportView.vue` 按 `runs.read` 门控提供类型选择
      （terminology/agent）+ JSON 输入 + Import 按钮，POST `/api/import/<kind>` 显示结果，新增 `/import` 路由用 `ImportView`。后端无改动。
      全量门禁 9 步全 PASS、2067 passed / 103 skipped。证据 `docs/evidence/SLICE-255-import-vue.txt`。
    - SLICE-256（迁 Ask AI 面板）~~已合并 `2d5eb44`~~：`web/src/views/AskAiView.vue` 按 `runs.read` 门控，自然语言输入 +
      Ask 按钮 POST `/api/ask-ai`（`{text, bindings: []}`）显示结果，新增 `/ask-ai` 路由用 `AskAiView`。后端无改动。
      全量门禁 9 步全 PASS、2070 passed / 103 skipped。证据 `docs/evidence/SLICE-256-askai-vue.txt`。
    - SLICE-257（迁聊天面板）~~已合并 `1c1d90c`~~：`web/src/views/ChatView.vue` 按 `chat.run` 门控，`GET /api/agents` 填选择器，
      发送 POST `/api/chat/stream`（`{agent, message}`）用 `ReadableStream` 读 SSE 块，`done` 追加 `reply`、`error` 追加 `error`、
      `progress` 忽略，消息日志按 you/agent/system 渲染，新增 `/chat` 路由用 `ChatView`。后端无改动。
      全量门禁 9 步全 PASS、2073 passed / 103 skipped。证据 `docs/evidence/SLICE-257-chat-vue.txt`。
      阶段 0 收口：20 个面板全部迁到 Vue，行为等价。
    - **阶段 1**：用户/角色/授权管理 + 统一登录（诉求 1+6）。角色定义 store + 用户绑定 store + `_capabilities_for` 运行时化 + 管理面板。
      - SLICE-258（角色定义 store）~~已合并 `b91327b`~~：`core/roles.py` 把能力常量 `_CAPABILITIES_*` 公开为
        `CAPABILITIES_ALL/BASE/OPERATOR/PUBLISHER`，`RoleDefinition`（name+capabilities+builtin+description，能力去重排序、
        name 白名单）、`RoleStore` 端口与错误、`BUILTIN_ROLES` 种子（admin/operator/ops/approver/publisher/developer/base 与现网一致）
        + `seed_builtin_roles()`；`registry/roles.py`/`roles_postgres.py` 提供文件/Postgres 双后端（`adk_roles` 幂等 insert-then-compare）；
        `console.py` 改导入、`_capabilities_for` 行为不变。后端对外接口无变化。
        全量门禁 9 步全 PASS、2079 passed / 104 skipped。证据 `docs/evidence/SLICE-258-role-store.txt`。
        下一步：用户绑定 store（subject→角色，租户维度）。
      - SLICE-259（用户绑定 store）~~已合并 `4042443`~~：`core/user_bindings.py` 加 `UserBinding`
        （tenant 白名单、subject 1..256、roles 去重排序且每项走角色名白名单）+ `UserBindingStore` 端口与错误；
        `registry/user_bindings.py` 文件后端落盘 `<root>/<tenant>/<sha256(subject)>.json`（任意 subject 不穿越路径），
        `registry/user_bindings_postgres.py` 用 `adk_user_bindings`（主键 `(tenant, subject)`，幂等 insert-then-compare）。
        后端对外接口无变化，绑定尚未被能力解析消费。
        全量门禁 9 步全 PASS、2085 passed / 105 skipped。证据 `docs/evidence/SLICE-259-user-binding-store.txt`。
        下一步：`_capabilities_for` 运行时化（读 role store + 用户绑定，fail-closed）。
      - SLICE-260（能力解析运行时化）~~已合并 `16acc65`~~：`build_console_app`/`run_console` 加 `role_store`，
        `_caps_for(caller)` 在未配置 store 时走内置角色表（行为不变），配置后按角色逐条读定义取并集；角色定义即完整能力集合，
        未定义角色贡献空集、并集为空回落基础能力；store 读失败与白名单外角色名一律 fail-closed 到基础能力并记日志。
        `_forbidden_if_missing` 改 async（44 处调用加 `await`），`/api/me`、`/api/overview` 与审批三处改用 `_caps_for`。
        CLI 加 `--role-store-dir`/`--role-store-db`（env `ROLE_DATABASE_URL`，互斥退出 2），启动幂等种子且不覆盖运维改过的内置角色。
        契约 `docs/contracts/console.md` 补能力来源与 fail-closed。
        全量门禁 9 步全 PASS、2093 passed / 105 skipped；`prove_it_works --only P13` PASS。证据 `docs/evidence/SLICE-260-capabilities-runtime.txt`。
        下一步：`/api/roles` 与 `/api/users` 管理接口（admin-only，写审计 role.define / user.bind）。
      - SLICE-261（角色与用户管理接口）~~已合并 `0b90c93`~~：能力词表新增 `roles.read`/`roles.manage`（只发给 admin；
        `tests/test_console_me.py` 的期望集合仅新增两项）。`GET/PUT/DELETE /api/roles` 与 `GET/PUT/DELETE /api/users`
        按能力先于配置与 body 检查；内置角色 DELETE 409 且编辑保留 builtin 标记；用户绑定默认限调用方租户，admin 可 `?tenant=`；
        写审计 role.define/role.remove/user.bind/user.unbind，审计失败不回滚。CLI 加 `--user-binding-store-dir|-db`
        （env `USER_BINDING_DATABASE_URL`）。`_seed_role_store` 对已存在的内置角色**只增不减**回填当前种子新增能力
        （会话确认的迁移），修掉旧 store 升级后 admin 缺少新能力的管理自锁。
        全量门禁 9 步全 PASS、2214 用例收集 / 105 skipped；`prove_it_works --only P13` PASS。证据 `docs/evidence/SLICE-261-roles-users-api.txt`。
        下一步：SLICE-262 让用户绑定并入能力解析（租户维度，fail-closed）。
      - SLICE-262（用户绑定并入能力解析）~~已合并 `9b584c3`~~：`_effective_roles` = token 角色 ∪ 该租户绑定角色，
        绑定按认证主体的 `caller.tenant`/`caller.subject` 查（请求参数无法影响）；并集只加不减；绑定 store 读失败
        记录日志后只用 token 角色（不剥夺、不放行）。其余语义不变，契约补「有效角色」说明。
        全量门禁 9 步全 PASS、2116 passed / 105 skipped；`prove_it_works --only P13` PASS。证据 `docs/evidence/SLICE-262-binding-capabilities.txt`。
        下一步：SLICE-263 前端「用户/角色」面板（Vue），接 `/api/roles` 与 `/api/users`。
      - SLICE-263（用户/角色管理面板）~~已合并 `178f193`~~：`web/src/views/RolesView.vue`（`roles.read` 门控，
        GET /api/roles 角色表 + 能力多选编辑，`roles.manage` 才显示保存/删除，内置角色无删除按钮）与
        `web/src/views/UsersView.vue`（绑定表 + 按角色勾选绑定/解绑）；`web/src/api/capabilities.ts` 28 项常量与后端集合
        双向相等（测试锁定）；新增 `/roles`、`/users` 路由与导航；重建 `web/dist/`。后端无改动。
        全量门禁 9 步全 PASS、2122 passed / 105 skipped；`npm run build` 成功。证据 `docs/evidence/SLICE-263-roles-panel.txt`。
        **ADR-0041 阶段 1（用户/角色/授权管理 + 统一登录）收口**：SLICE-258..263 交付了角色定义 store、用户绑定 store、
        能力解析运行时化（fail-closed）、绑定并入解析、管理接口与管理面板。下一阶段为阶段 2（Agent 中心总览）。
    - **阶段 2**：Agent 中心总览（诉求 2）。registry/lifecycle 重组为 agent 旅程视图。
      - SLICE-264（Agent 中心总览）~~已合并 `357439b`~~：`web/src/views/AgentHubView.vue` 按 `registry.read` 消费
        `GET /api/registry`，聚合计数卡（Agent/版本/发布中/已弃用/已退役/远端）、lifecycle 分布条与按 id 分组的版本旅程表
        （生命周期、评测、工件/信任、发布时间、local/remote）；`/agents` 路由从占位页切换；顺带修 `stat-card` 布局
        （标签与数值原本同行）。全量门禁 9 步全 PASS、2126 passed / 105 skipped。证据 `docs/evidence/SLICE-264-agent-hub.txt`。
    - **页面可配置能力补齐**（用户反馈：模型、注册等应在页面配置而非后台代码）——按接口已具备的能力逐个补前端表单：
      - SLICE-265（模型默认值）~~已合并 `9031de2`~~：`ModelView.vue` 增加「默认模型」区，`GET /api/model-config` 显示当前值，
        `model.write` 下 PUT 保存，400 提示「模型名无效」；后端无改动。全量门禁 9 步全 PASS、2128 passed / 105 skipped。
        证据 `docs/evidence/SLICE-265-model-config-form.txt`。
        - SLICE-266（策略保存）~~已合并 `1ed7cb7`~~：`PolicyView.vue` 在 `policy.write` 下提供 JSON 文本域与保存，
          本地 `JSON.parse` 预检，400「策略无效」/403「策略被拒绝」，网络失败有兜底文案；只读用户仍看格式化 JSON。
          全量门禁 9 步全 PASS、2130 passed / 105 skipped。证据 `docs/evidence/SLICE-266-policy-save.txt`。
        - SLICE-267（注册表动作）~~已合并 `52f9bc4`~~：本地卡片加「加载」「卸载」（`registry.load`），
          底部「注册 Agent 清单」（`registry.publish`，本地 JSON 预检 → `POST /api/import/agent`）；加载失败按服务端
          `error` 码给出具体文案（名称冲突/版本退役/工件缺失或不可信/沙箱不可用/达到上限）。实机验证：按需加载、卸载、
          清单注册各一次成功。全量门禁 9 步全 PASS（2237 用例收集）。证据 `docs/evidence/SLICE-267-registry-actions.txt`。
        - SLICE-268（连接器与凭据表单）~~已合并 `6c8cbc8`~~：两个面板加 `connectors.manage` 表单与「禁用」；
          连接器字段（ID/租户/类型/Base URL/路径前缀/凭据引用/超时/方法），凭据只登记 `secret://` 引用、
          页面不发送任何密钥材料（测试扩展为两面板 × 四个禁名字段）。实机：注册凭据/连接器、禁用、再注册各成功。
          证据 `docs/evidence/SLICE-268-connector-forms.txt`。
        - SLICE-269（审批与工具授权决定）~~已合并 `0d3968f`~~：审批面板「批准/拒绝」+ 共享理由框（`approvals.decide`），
          工具授权 pending 行「批准/拒绝」（`grants.decide`），错误码映射到固定文案；实机批准 `demo-approval-1` 成功。
          证据 `docs/evidence/SLICE-269-decide-buttons.txt`。
        - SLICE-270（对端与远端目录）~~已合并 `0716217`~~：对端注册表单 + 禁用、远端 Agent 登记（卡片 URL + 可选凭据引用）；
          错误码按服务端实际返回映射（含 card_unreachable/card_unauthorized/card_too_large/card_invalid/card_name_mismatch）。
          实机：注册与禁用对端成功；不可达卡片返回 card_unreachable。证据 `docs/evidence/SLICE-270-peers-forms.txt`。
        **「页面可配置能力补齐」收口**：模型默认值、访问策略、注册表加载/卸载与清单注册、连接器与凭据、
        审批与工具授权决定、对端与远端目录均可在页面操作；带签名工件的发布当时仍保留 CLI（私钥不进浏览器；阶段 5 已改为 SLICE-280/281 的页面一键发布）。
      - SLICE-271（Agent 中心跨租户与评测下钻）~~已合并 `65f36c1`~~：admin 显示租户切换
        （`GET /api/registry?tenant=`，非 admin 直连他租户仍由服务端 403）；有评测报告的版本行可内联查看
        `/{tenant}/{id}/{version}/eval`。实机：`?tenant=local` 三条、bot_a@1.0.0 评测 200（2/2）。
        全量门禁 9 步全 PASS、2143 passed / 105 skipped。证据 `docs/evidence/SLICE-271-hub-tenants.txt`。
        **ADR-0041 阶段 2（Agent 中心总览）收口**：注册数、lifecycle 分布、版本、评测、跨租户与远端目录都已在
        `/agents` 呈现。下一步为阶段 3（安全合规聚合视图，诉求 5）。
    - **阶段 3**：安全合规聚合视图（诉求 5）。审计完整性、扫描、密钥轮换、策略概览。
      - SLICE-272（安全聚合接口）~~已合并 `c6abf26`~~：`GET /api/security`（`ops.read`）返回 audit/keys/policy/scans；
        `?verify=1` 校验文件审计链（10 秒超时、60 秒缓存、固定错误码）；密钥只给 id 与计数。
        首轮验证 REJECT 的 B1/B2 与 S1/S2 已修（`ae8449a`），第二轮独立验证 PASS 并亲自复跑 `--full`
        （2151 passed / 105 skipped）。
      - SLICE-273（安全面板 + 三处残余）~~已合并 `2796404`~~：`SecurityView.vue`（`/security`，`ops.read`）四张卡
        与「校验审计链」；`scans` 严格按 schema 校验且只回传两个计数，审计失败给 `audit_unavailable`，
        非法租户路径给 `credential_store_unavailable`。四轮独立验证（首轮 PASS 带 1 个 S + 3 个 N，二、三轮 REJECT，合并前复验 PASS），
        最终门禁 2168 passed / 105 skipped。证据 `docs/evidence/SLICE-273-security-panel.txt`。
      - SLICE-274（CI 扫描汇总脚本）~~已合并 `da97227`~~：`scripts/security_report.py` 把 SARIF 与
        pip-audit JSON 汇总成 `docs/contracts/security_report.schema.json` 形状；只有 `accepted`
        （或缺 status）的压制算关闭，兼容两种 pip-audit JSON 布局；`generated_at` 为 UTC 秒级；
        输入/形状/输出不可写一律退出 2，成功时临时文件 + `os.replace` 原子替换。
        `docs/guides/operations.md` 补生成步骤。两轮验证（首轮 REJECT 写盘失败退出 1、压制误算、
        非原子写；第二轮 REJECT 空 basename 抛 `ValueError`；修后 PASS），最终门禁 2212 passed / 105 skipped。
        证据 `docs/evidence/SLICE-274-security-report.txt`。
        **ADR-0041 阶段 3（安全合规聚合视图）收口**。下一步为阶段 4（生态展示）。
    - **控制台视觉改造（用户 2026-11-24 要求，参考 Cloudflare 仪表盘）**：
      - SLICE-275（视觉基座）~~已合并 `2a2357d`~~：`tokens.css` 设计令牌、26 个内联图标、五组侧栏
        （25 个面板入口，旧导航只有 10 个）、顶栏租户/主体、窄屏抽屉；`auth.resolved` 门控修掉
        「能力未到、视图先挂载、页面空白」的竞态，并处理 401 清 token 与网络失败提示。
        两轮验证（REJECT 登录路径绕过门控 → 修 → PASS），最终门禁 2179 passed / 105 skipped。
        截图 `docs/evidence/ui/SLICE-275-*.png`。证据 `docs/evidence/SLICE-275-visual-shell.txt`。
      - SLICE-276（通用组件与可配置首页）~~已合并 `6e23653`~~：新增 `PageHeader` / `EmptyState`，
        首页有按能力过滤的快捷操作、指标卡、最近活动与「自定义首页」（三区块显隐存 localStorage）。
        验证发现 `/api/audit` 对查询后端返回倒序窗口却按「取末尾 N 条」截断，已在 `_query_events`
        统一升序并补审计与 RAG 的倒序用例。两轮验证（REJECT → 修 → PASS），门禁 2189 passed / 105 skipped。
      - SLICE-277（页头收口）~~已合并 `43afaff`~~：25 个视图统一用 `PageHeader`，业务页各一句说明（占位页无说明）；
        首轮验证 PASS 后按反馈改准六处副标题（3 处内容不符 + 3 处措辞偏大）。门禁 2192 passed / 105 skipped。
      - SLICE-278（空态与表格收口）~~已合并 `b05eb28`~~：六个列表页用 `EmptyState`，五个表格页
        `.table-wrap` 横向滚动，文本型指标缩字号，Agent 中心租户表单进工具条，徽章改用状态令牌。
        两轮验证（PASS + 1 个 S 视觉回归 → 修 → PASS），门禁 2197 passed / 105 skipped。
        **视觉改造四切片（275–278）收口**。SLICE-274 随后完成；下一步为阶段 4（生态展示），
        然后是阶段 5（开发向导，先写 ADR-0043）。
    - **阶段 4**：MCP/API 生态展示（诉求 4）。MCP server、A2A 对端、连接器、可复用工具 + 接入引导。
      - SLICE-279（生态展示页）~~已合并 `a49a5e3`~~：`/ecosystem`（导航「开发」组）统一列出工具目录、
        连接器（`kind=mcp` 即 MCP 服务器）与 A2A 对端，各按 `tools.read` / `connectors.read` / `peers.read`
        取数，只有三项都无权才整页拒绝；四张可复制的接入引导卡（登记 MCP 连接器、暴露为
        streamable-http MCP 服务、登记与授权 A2A 对端）；工具表按来源筛选；无权限项显示「—」。
        四轮验证（首轮 PASS 带 2 个 S，第二轮 2 个边界 B，第三轮 1 个 B + 5 个 N，第四轮 PASS），
        最终门禁 2220 passed / 105 skipped。截图 `docs/evidence/ui/SLICE-279-ecosystem.png`。
        **ADR-0041 阶段 4 收口**。下一步阶段 5（先写 ADR-0043）。
    - **阶段 5**：Agent 开发向导（诉求 3）。把 `compose` 模板做成多步 UI 向导。
      - SLICE-280（compose 后端与一键发布）~~已合并 `cd03d16`~~：新增 `registry.compose`（admin + publisher），
        `GET /api/compose/templates`、`POST /api/compose/preview`、`POST /api/compose`；
        `console` 四个 `--compose-*` 密钥参数 all-or-none（部分退出 2、坏密钥退出 1）；
        `AuditEvent.template_id` 与 `agent.compose` 审计（不含指令原文）。
        两轮验证（首轮 REJECT：深层嵌套 JSON 触发 `RecursionError`，预览与发布都 500；超长字段触发
        `PackagingError`，预览 500、发布 503；补 400 `compose_invalid` 与字段上限后 PASS），最终门禁 2237 passed / 105 skipped；
        用户要求的 `prove_it_works` 全量 14/14 PASS。证据 `docs/evidence/SLICE-280-compose-backend.txt`。
      - SLICE-281（新建 Agent 向导）~~已合并 `7a49408`~~：`/agents/new` 四步向导（模板 → 参数 → 预览 → 发布），
        模板与预览要求 `registry.publish`、发布要求 `registry.compose`，未配置密钥时给可复制的 CLI 命令；
        错误码固定文案、前端上限与契约一致、无 `v-html`。实机（`--ui vue`，admin）走完整流程，
        注册表出现 `shot_bot@2.0.0`，审计三条 `agent.compose`。两轮反馈修正后终验 PASS（首轮 PASS + 1 S；第二轮发现
        `watch(step)` 异步清空让成功横幅不渲染，删掉冗余提示后复验 PASS），门禁 2245 passed / 105 skipped。
        截图 `docs/evidence/ui/SLICE-281-wizard-{form,preview,published}.png`。
        **ADR-0041 阶段 5 收口，ADR-0041 全部阶段完成**。下一步按缺口清单选。

    - **缺口清理（282–287，2026-11-25）**：
      - SLICE-282 `--audit-file` 读取兼容裸事件 ~~已合并 `c3d8898`~~（#319）：`query_events` 先按
        `AuditRecord` 再按 `AuditEvent` 解析，写入格式与 `verify-audit` 不变；契约收窄为
        「`serve-audit --out` 不能直接托管纯裸文件」。两轮验证。
      - SLICE-283 凭据接口租户校验 ~~已合并 `b02cb77`~~（#320）：`GET /api/credentials` 与 disable
        统一校验解析后的租户（非法 400 `unsafe_tenant`），disable 另校验 `credential_id`
        （400 `invalid_credential`）。两轮验证。
      - SLICE-284 publisher 获得 `ops.read` ~~已合并 `075cbd6`~~（#321）：总览/配额/RAG/语义/安全面板可见
        （安全面板：配置审计后端时审计计数按调用方租户、内存/文件回退为进程级；凭据计数按调用方租户；
        扫描与签名密钥 id 为进程级；均无密钥值），能力词汇表不变；`test_console_me.py` 的 PUBLISHER 字面量经用户同意更新。四轮验证均为文档措辞。
        截图 `docs/evidence/ui/SLICE-284-publisher-home.png`。
      - SLICE-285 表格窄屏最小宽度 ~~已合并 `0acbc23`~~（#322）：`.table-wrap table { min-width: 720px }`，
        480px 下横向滚动。截图 `docs/evidence/ui/SLICE-285-tools-narrow.png`。
      - SLICE-286 审计同刻顺序 ~~已合并 `1b97f8e`~~（#323）：`_query_events` 按 `(timestamp, event_id)`
        排序，内存/文件/HTTP 后端一致；契约写明 1000 条读取窗口。两轮验证（第二轮指出测试的文件写序让文件后端在旧代码上误绿，
        改为 a、b 写序后两种后端都能区分修复）。
      - SLICE-287 compose 签名密钥运维手册 ~~已合并 `634b22b`~~（#324）：`docs/guides/compose-signing.md`
        （生成、四个参数、信任集、加法轮换、泄露撤销、最小权限、~~文件注册表不校验构建签名~~
        ——已由 SLICE-291 / ADR-0044 在载入侧统一校验），
        `operations.md` 链接；负向断言锁定「compose 只签名不验签」。两轮验证。
      - ~~仍记录未做~~（前三项已由 288–290 修复，见下节）：~~侧栏入口不按能力隐藏~~；~~9 个视图的表格
        未包在 `.table-wrap`~~；~~自定义角色授予 `connectors.manage` 后可跨租户停用凭据~~。

    - **新观察清理（288–290，2026-11-25）**：
      - SLICE-288 侧栏按能力过滤 ~~已合并 `703ccda`~~（#326）：每个入口加 `v-if="auth.hasCapability('...')"`，
        分组按组内能力隐藏；向导入口与中心「新建」按钮统一为 `registry.publish` 或 `registry.compose`。
        同批包含镜像的 `libzstd1` 安全更新（CI 报出后补装）。验证两轮，另有 CI 后补的安全更新提交。
        截图 `docs/evidence/ui/SLICE-288-publisher-nav.png`。
      - SLICE-289 其余表格并入滚动容器 ~~已合并 `b2e6baa`~~（#327）：9 个视图的表格包进 `.table-wrap`，
        表格级 `v-if`/`v-else-if` 移到包裹元素，复用 720px 最小宽度。两轮验证。
        截图 `docs/evidence/ui/SLICE-289-roles-narrow.png`。
      - SLICE-290 凭据停用跨租户校验 ~~已合并 `63e5baf`~~（#328）：非 admin 跨租户 disable 返回 403；
        旧行为是 200 并真的停用（实测确认）。两轮验证。
      - ~~仍记录未做：`scripts/demo_seed.py` 的构建签名缺口~~ 已由 SLICE-300（`38c7c5b`）
        修复；同刻事件超过 1000 条读取窗口的极端情形已由 SLICE-301（`295e356`）的
        稳定排序与游标分页关闭。

    - **构建签名载入收口（291，2026-11-25）**：
      - SLICE-291 载入侧校验构建签名 ~~已合并 `e045b7d`~~（#330，ADR-0044）：`load_agent`、
        控制台 `POST /api/registry/load`、`serve-triggers` 每次 fire 在 `in_process`（含历史无层级）
        记录上强制 `--builder-keys`/`ADK_BUILDER_KEYS`；五个命令接线；`sandboxed` 保持豁免。
        第一轮验证 REJECT（`serve-triggers` 仍可执行未验签记录），修复后第二轮 PASS，
        第三轮确认文档修正。证据 `docs/evidence/SLICE-291-load-builder-trust.txt`。
      - 原「文件注册表不校验构建签名」的限制随之关闭；剩余设计级事项（1000 条读取窗口）后由 SLICE-301 关闭，
        另记一条演示脚本的小缺口（见上）。
      - 原计划的 SLICE-292（手册与 PROGRESS 收口）内容已随 291 与本次记录交付，不再单列。

    - **手机屏适配（292，2026-11-25）**：
      - SLICE-292 全部视图手机布局 ~~已合并 `5dd0bf3`~~（#332）：600px 断点覆盖外壳、页头、
        行内控件、表单单列、表格触屏滚动与聊天输入贴底（`env(safe-area-inset-bottom)`）；
        视口加 `viewport-fit=cover`；`web/dist/` 重建。390×844 实测 27 个路由无页面级横向溢出，
        截图 `docs/evidence/ui/SLICE-292/`。一轮独立验证 PASS。

    - **治理引导（293，2026-11-25）**：
      - SLICE-293 治理导航分组与空状态引导 ~~已合并 `1461d08`~~（#334）：治理分组按
        「访问控制 / 审计与合规 / 集成与配额」三个子标题归位；`EmptyState` 支持标题、说明与动作；
        13 个治理页换用带引导的空状态，英文内部错误串改为带配置方式的中文提示。
        两轮验证（首轮指出用户绑定与检索两页遗漏、`.empty-state` 样式重复，已补齐）。
        证据 `docs/evidence/SLICE-293-governance-guidance.txt`、`docs/evidence/ui/SLICE-293/`。

    - **验收脚本构建信任（295，2026-11-25）**：
      - SLICE-295 验收脚本补齐 `--builder-keys` ~~已合并 `24a4f7d`~~（#336）：SLICE-291 收紧后，
        `prove_it_works.py` 的六处服务调用漏了构建信任集，端到端 6 项失败；补齐后 14/14 PASS。
        新增静态锁定测试，切片检查表增加「收紧载入/执行契约时同步全部消费端」的检查点，
        `adk-slice` skill 同步补了两条（本地 skill，不入库）。两轮修复轮（首次插入顺序错误与
        下一片红测试污染门禁，均已修正并复跑）。

    - **控制台使用手册（294，2026-11-25）**：
      - SLICE-294 HTML 使用手册 ~~已合并 `e4aedcb`~~（#338）：`docs/guides/console-ui.html`
        单文件、无外部依赖；`GET /guide` 免鉴权返回，侧栏「设置」组有入口；覆盖 27 个页面、
        两条完整流程与错误对照。两轮验证（首轮指出三处错误表措辞与实现不符，已改）。
        证据 `docs/evidence/SLICE-294-console-guide.txt`、`docs/evidence/ui/SLICE-294/`。
      - ADR-0045（模型提供方与密钥配置）同日确认接受：默认方案 A（纯引用），方案 B
        （只写加密录入）由启动参数显式开启并满足五条前提。
      - SLICE-296 模型提供方记录与接口（方案 A）~~已合并 `f0a6ac8`~~（#340）：
        `ModelProviderRecord` 与 `FileModelProviderStore`，`GET/PUT /api/model-providers`
        （`model.read`/`model.write`），`console --model-providers-dir`；审计写
        `model.configure`，记 provider_id、provider_kind 与 `secret_ref` 键名，
        `AuditEvent` 新增两个可选字段并同步两份契约 schema。四轮独立验证：
        首轮 PASS 带 S-1（60–64 字符 id 触发 500）/S-2（审计缺类型与引用名），
        修复后第二轮 REJECT（`audit_record.schema.json` 未同步），三轮 PASS，四轮窄验 PASS。
        证据 `docs/evidence/SLICE-296-model-providers.txt`。
      - SLICE-297 模型密钥只写录入（方案 B）~~已合并 `4c0319a`~~（#342）：
        `PUT/DELETE /api/model-providers/{id}/key`（只写、`sk-…abcd` 掩码、未知提供方 404、
        无 KEK/后端失败 503、非法 key 400），`DELETE` 无 KEK 也能吊销；列表带
        `key_configured`/`key_hint`；`console --model-key-entry` 要求存储目录在仓库外，
        否则退出 1。`FileModelProviderKeyStore` 只落信封密文与掩码，AAD
        `adk-model-provider:<id>`；`ModelKeyResolver` 解密失败写 `model.key_failed`。
        两轮独立验证（首轮 PASS 带 S-1 短 key 掩码泄露、S-2 resolver 读取异常绕过审计，
        修复后复验 PASS）。证据 `docs/evidence/SLICE-297-model-key-entry.txt`。
      - SLICE-298 模型提供方运行时解析 ~~已合并 `5141db5`~~（#344）：
        `build_model` 经 `resolve_model_config` 按 `(kind, 模型名)` 从启用记录补
        `api_key`/`api_base`（不改模型名）；`FileProviderLookup` 先取方案 B 密文、再取
        `secret_ref` 环境变量，失败回落到现有默认；解密失败写 `model.key_failed`（有事件
        循环时）或脱敏日志。`console`、`serve`、`serve-many`、`serve-a2a`、`serve-triggers`
        都接受 `--model-providers-dir`；列表接口顶层加 `key_entry`。两轮验证：本地首轮
        PASS（5 个 N 提示，均不阻断）；随后 CI 的 secrets 步命中夹具 `secret://` 引用，
        加 allowlist 后复验 PASS。证据 `docs/evidence/SLICE-298-model-runtime.txt`。
      - SLICE-299 模型页提供方与密钥表单、手册 ~~已合并 `65654c1`~~（#346）：
        `ModelView.vue` 列出提供方（类型/模型/端点/掩码/状态），admin 可创建或更新记录；
        `key_entry` 开启时每行可只写保存密钥、吊销，密码框 + 掩码 + 固定中文错误映射，
        写操作按 `model.write` 门控。重建 `web/dist/`；`console-ui.html`「模型」一节补
        提供方、密钥、掩码与解析顺序。独立验证 PASS（2 个 N：密钥路径未编码、列表错误
        文案偏 404，均无实际风险）。实机截图 `docs/evidence/ui/SLICE-299-model.png`；
        证据 `docs/evidence/SLICE-299-model-page.txt`。
        **ADR-0045（模型提供方与密钥配置）至此全部交付**：记录与接口、只写加密录入、
        运行时解析、页面与手册。
      - SLICE-300 演示种子补构建签名 ~~已合并 `38c7c5b`~~（#348）：`demo_seed.py` 的
        `in_process` 工件同时写发布与构建签名，输出与 `docs/demo/pilot-demo.md` 增加
        `ADK_BUILDER_KEYS` 与 `--builder-keys`；新增 3 条用例，其中一条用 `load_agent`
        真实载入。独立验证 PASS。证据 `docs/evidence/SLICE-300-demo-seed-builder.txt`。
      - SLICE-301 审计读取的稳定排序与游标 ~~已合并 `295e356`~~（#350）：文件与 Postgres
        截断统一按 `(timestamp, event_id)`；`GET /v1/events` 增加开区间
        `before_timestamp`+`before_event_id`（成对、仅 desc，400 `invalid_cursor`），
        文件/HTTP/Postgres 查询与 `AuditQuery` 协议同步；控制台按游标向前翻页。
        两轮验证（首轮 PASS，仅收紧 spec 判据措辞后复验 PASS）。证据
        `docs/evidence/SLICE-301-audit-cursor.txt`。Postgres 游标 SQL 因本机无
        `TEST_POSTGRES_URL` 未在真实库执行。
      - SLICE-302 控制台深色主题 ~~已合并 `e1806f0`~~（#352）：`tokens.css` 增加
        `[data-theme="dark"]` 覆盖，`index.html` 挂载前按 `localStorage["adk_theme"]`
        或系统偏好设置主题，顶栏按钮切换并持久化；`style.css` 去掉写死颜色，
        强调色文字改用 `--text-inverse`（暗色对比度 6.69:1）。重建 `web/dist/`，
        手册设置一节说明。两轮验证（首轮 PASS 带 1 个 S 对比度，修复后复验 PASS）。
        截图 `docs/evidence/ui/SLICE-302-dark.png`、`SLICE-302-dark-phone.png`；
        证据 `docs/evidence/SLICE-302-dark-theme.txt`。
        剩余设计级事项：沙箱子进程不继承模型提供方 lookup（SLICE-298 的 N5）经复核
        不影响实际行为——worker 的 `build_model` 只是标签，真实模型由父进程构造；
        视觉改造只剩命令面板未做。
      - SLICE-303 售后演示 mock 生态 ~~已合并 `57a560c`~~（#354）：`scripts/mock_services.py`
        提供 ITSM 工单、夸克附件（≤1 MiB，元数据不回内容）与企业微信 webhook，
        固定 Bearer token；`docs/demo/support-agent.md` 定义角色、端点与真实接入顺序。
        场景定为「WorkBuddy 当前端，ADK 当售后专家后端」，个人微信自动化明确不做。
        证据 `docs/evidence/SLICE-303-support-mock.txt`。
      - SLICE-304 售后演示的计划审批 ~~已合并 `d74c5b9`~~（#355）：
        `scripts/prove_support_demo.py` 自起 mock 并跑顺序计划——`answer`（无审批）+
        `ticket`（L3，人工审批）→ 建单 → 企业微信通知 → 审计链校验；拒绝时打印
        `PASS deny path left no ticket or message` 并退出 2。3 条用例。两轮验证
        （首轮 PASS 带 1 个 S：拒绝路径缺正向断言，修复后复验 PASS）。
        证据 `docs/evidence/SLICE-304-support-plan.txt`。
      - SLICE-305 售后演示接入控制台 ~~已合并 `0b028ab`~~（#357）：
        `prove_support_demo.py` 新增 `--approvals-dir`、`--audit-file`、`--interactive`、
        `--wait-seconds`，交互模式停在「审批」页等人点击，超时打印 `TIMEOUT` 退出 3；
        `scripts/support_demo_register.py` 把 mock ITSM 与夸克登记为控制台可见连接器
        （`mock-token-ref` 启用绑定，`secret://local/mock_token`），可重复运行。
        实机用控制台 `POST /api/approvals/<id>` 批准后演示跑到 `ALL PASS`，
        `GET /api/connectors` 列出两个连接器。5 条用例。两轮验证（首轮 PASS 带
        2 个 N：登记脚本重复运行抛 `CredentialConflict`、超时残留请求 `expires_at`
        为空，修复后复验 PASS）。
        证据 `docs/evidence/SLICE-305-support-console.txt`。
      - SLICE-306 售后演示的 A2A 入口 ~~已合并 `9f044d8`~~（#359）：
        `scripts/support_a2a_agent.py` 把同一计划包成 ADK `BaseAgent`
        （`support_flow`，四个 `SUPPORT_*` 环境变量 + `SUPPORT_MOCK_TOKEN`），
        拒绝与超时转成固定中文文本、HTTP 200 返回；`scripts/prove_workbuddy_a2a.py`
        假 WorkBuddy 客户端自起 mock 与 `serve-a2a`，校验匿名 401、批准建单、
        `--deny` 退出 2、`--interactive` 超时退出 3；`support_demo_flow.py` 抽出共用
        计划与 agent。同切片修复平台缺陷：`install_tool_guard` 跳过未声明工具回调的
        自定义 `BaseAgent`（原先 `serve-a2a --agent` 直接 `AttributeError` 退出）。
        5 条用例 + 1 条守卫用例。三轮验证（首轮 PASS 带 2 个 S：证据误列 `--fast` 的
        `sast`、文档称超时返回 JSON-RPC 错误；第二轮 PASS 带 3 个 N，修完后第三轮 PASS）。
        证据 `docs/evidence/SLICE-306-support-a2a.txt`。
        下一步：换真实 WorkBuddy Enterprise OpenAPI（需要操作员账号的 `ck_`/`pt_` 密钥）、
        夸克官方 Skill 与企微自建应用回调。

其余方向从 `docs/specs/ROADMAP.md` 的里程碑状态里选。

16. 2026-11-24 新增要求与 SLICE-272 的验证残余：
    - **安全聚合接口残余**：~~三项已由 SLICE-273（`2796404`）修复~~（scans 严格按 schema 校验、审计失败给 `audit_unavailable`、租户路径非法给 `credential_store_unavailable`）。`/api/credentials` 对调用方自身非法租户的同类问题~~已由 SLICE-283（`b02cb77`）修复~~（另有 disable 的 `credential_id` 校验）。
    - **控制台视觉改造**：~~SLICE-275 到 278 已全部合并~~。残余取舍：~~`.table-wrap` 无可滚动的最小宽度~~（已由 SLICE-285 `0acbc23` 加 720px 最小宽度）；
      ~~深色主题~~ 已由 SLICE-302（`e1806f0`）交付；命令面板仍未做。
    - **同期发现的既有缺口（已修，282–287）**：`--audit-file` 裸事件读取由 SLICE-282 修复；
      `publisher` 缺 `ops.read` 由 SLICE-284 修复；同刻事件顺序由 SLICE-286 定为 `event_id` 升序；
      `/api/credentials` 调用方非法租户 500 由 SLICE-283 修复；`.table-wrap` 最小宽度由 SLICE-285 修复；
      compose 密钥运维手册由 SLICE-287 交付。详见上方「缺口清理（282–287）」。
    - **仍记录未做的新观察**：见上方「新观察清理（288–290）」末尾的清单。
    - **阶段 5 页面一键发布已交付**：ADR-0043 已入库（`docs/decisions/ADR-0043-console-compose-signing.md`），
      SLICE-280（后端）与 SLICE-281（向导）已合并。用户按硬规则单独同意的新增 `registry.compose` 与
      `tests/test_console_me.py` 两处字面量断言已落地。密钥托管、轮换与最小权限的运维手册由
      SLICE-287（`634b22b`）交付，见上方「缺口清理（282–287）」。

MCP 和 A2A 路径都已经通过 `AuditedRunner` 补上 `agent.run` 审计和配额。A2A 消费方的出站调用由 `a2a_egress.AuditTransport` 审计，见 SLICE-095。A2A 的 executor 用 `isinstance(runner, Runner)` 检查，代理靠 `__class__` property 通过，升级 ADK 时要复核。

配额表启用了 Postgres RLS，策略依赖 `app.tenant_id`。生产连接必须是表的属主，不能用超级用户或 `BYPASSRLS` 角色，否则策略不生效。建表步骤会自动 `ENABLE` 和 `FORCE`，连接角色没有 `ALTER TABLE` 权限时启动会失败。

## 恢复步骤

1. 读 `CLAUDE.md`、`docs/specs/ROADMAP.md`、本文件。
2. 跑 `python scripts/check.py --fast` 确认基线。
3. 从上面“下一刀建议”或 ROADMAP 候选里挑一个，先写 `docs/specs/SLICE-xxx.md`，先红后绿。

