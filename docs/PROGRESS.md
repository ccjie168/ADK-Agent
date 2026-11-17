# 项目进度登记

更新日期: 2026-11-16
分支: slice-127-trigger-scheduler（基于 master 59ae49a）
最新提交: `66843e6` feat: add the trigger schedule loop and retries (SLICE-127)
状态: 可交接暂停，工作区干净（只留本地工具目录未跟踪）

## 本次暂停交接

- 代码在 `slice-127-trigger-scheduler` 分支，`66843e6`，基于 master `59ae49a`。SLICE-116 到 126 已通过 PR #22、#24、#25、#26、#28、#29、#30、#31、#32、#33、#34 合并；调度循环的 PR 尚未开。工作区干净，未跟踪的 `.agents/`、`.claude/agents/`、`.claude/skills/`、`.claude/worktrees/`、`package.json`、`package-lock.json` 是本地工具，不入库。
- 最近门禁: `--fast` 与 `--full` 都是 1358 passed, 80 skipped；调度、服务与 CLI 用例 23 passed。
- 治理规则已改为切片级自动：spec 到合并不再逐次确认，合并前必须有独立只读验证代理。
- 演示进程已全部停止: 控制台 8081 到 8085、8091 到 8094、8101、8102、mock IdP 9000、审计 8010、headless Edge 9223 到 9227。`adk-registry` 与 `adk-postgres-070` 容器在 127.0.0.1:5000 与 55432。演示数据留在 `C:/Users/Jie/AppData/Local/Temp/` 下的 `adk-ui-demo/`、`adk-ui-shell/`、`adk-116-seed/`、`adk-117-roles/`、`adk-118-history/` 与 `adk-119-drill/`，需要时重建。
- 下一刀: agent 级沙箱先写 ADR，再做实现；之后是凭据密钥后端。两者都要人工确认 ADR。
- 恢复顺序: 读 `CLAUDE.md`、`docs/specs/ROADMAP.md`、本文件，跑 `./.venv/Scripts/python.exe scripts/check.py --fast`，再从缺口清单挑一项。

## 一句话

企业级 ADK agent 平台的 M0 到 M5 已全部收口，另加控制台可见性、审计客户端接入、只读运营视图、OIDC 解析器、控制台 OIDC 接线、服务面 OIDC 接线、MCP HTTP 认证、MCP principal 注入、共享配额、审批收件箱、MCP 运行审计、指标与 trace、A2A 运行审计、审批过期、服务指标端点、审批归档、配额行级隔离、审计轮转签名、模型熔断、文件状态备份恢复、压测基线、SSE 有界缓冲、入口限流、MCP/A2A 限流、审计密钥轮换、可选的会话租户隔离和审计只读查询和控制台共享审计、工件类型、工件存储、带签名发布、验签加载、注册表启动和市场视图、Postgres 注册表、控制面、命令接线、按需加载、报告集中存储、工具目录、生命周期存储与拦截、工具授权请求存储与 MCP/A2A 工具守卫与临时授权合并、审批入口、用量视图、卸载置换、跨副本限流、连接器存储、连接器执行、控制面、工具目录合并、健康检查、A2A peer 身份、管理面、迁移收口、远端目录记录、市场页合并、出站审计、审计 Postgres 存储与数据库接线、审批 Postgres 收件箱与接线、多副本清单与运维手册、发行完整性八十八个切片。本地门禁全绿。OIDC 身份链路完整，多副本配额在 Postgres 上共享并由 RLS 约束，审批可以跨进程走通并有截止时间和归档，MCP 和 A2A 调用都有审计和配额，控制台、两个网关和 MCP 都有 Prometheus 指标，trace 能跨边界传播，审计链支持分段和 HMAC 验签，模型 provider 有熔断，注册表和审计可以打包备份并安全恢复，配额与审计吞吐有可复现的压测基线，控制台 SSE 在慢客户端下内存有界且会报告丢弃数，控制台、三个独立服务、MCP 和 A2A 都按调用方限流，审计签名密钥可轮换而不作废旧记录，会话可以按租户隔离，审计服务可按租户查询事件，控制台的审计与运行面板读同一份共享数据，工件可按 digest 存在文件或 Postgres，发布时可用 Ed25519 签名，注册的工件可按引用验签加载成 agent，控制台与 MCP 可直接从注册表启动，市场页显示工件摘要与验签状态，并附演示种子与截图，已发布版本可从共享 Postgres 读写而不依赖共享卷，控制面服务按契约发布、读取并接收工件字节，四个命令可用 `--registry-url` 读写同一份目录，市场页可按需验签加载版本并直接开聊，评测报告与版本同库并由控制台跨副本读取，工具目录可按租户展示来源、数据分级和授权关系。ADR-0010 已签字，生命周期状态可存储、读取与审计，退役版本无法再被加载或启动。ADR-0011 已签字，工具临时授权请求可存储、审批与到期判断，MCP 与 A2A 运行路径也按允许清单拦截工具，已批准的临时授权可按版本合并放行，控制台与 CLI 可申请、审批并留痕，Grants 面板显示用量与即将到期，按需加载的版本可卸载并同位置换。ADR-0012 已签字，限流计数可走 Redis 跨副本共享并在故障时回退。ADR-0013 已签字，连接器可注册、按租户列出并停用，并能在工具网关里按出站策略执行，控制台与 CLI 也能管理连接器，工具目录会显示已启用连接器及其授权版本，连接器可主动探测并给出结构化健康结论。ADR-0014 已签字，A2A 提供方按 peer 身份认证并按 `read`/`invoke` 授权，审计身份随 peer，legacy 共享单 token 模式保留且与 peer 模式互斥，peer 与授权可在控制台和 `peers` 命令里管理，两种模式的互斥有库层与 CLI 双重验证，迁移步骤见 `docs/guides/a2a-peer-migration.md`。远端 peer 暴露的 agent 可作为目录记录登记，card 摘要固定后刷新会区分固定、已变化与不可达，但暂不可从控制台加载；市场页会显示来源与信任徽标，并提供刷新入口。ADR-0015 已签字，消费者出站调用按 `a2a.call` 与 `egress=third_party` 审计，跨组织审计边界只覆盖本地侧，按 trace id 关联。ADR-0016 已签字，审计可按租户写入 Postgres、并发写安全并可整链验证。审计服务、控制台与网关可用 `--audit-db`/`AUDIT_DATABASE_URL` 共享同一份 Postgres 审计，`serve-audit` 文件与数据库双后端均可用。ADR-0017 已签字，审批请求与决定可按行存入 Postgres，条件 `UPDATE` 保证并发决策只生效一次，过期判定、归档与删除语义对齐文件实现，控制台、CLI prune 与执行器已共享同一份审批，两个进程的轮询与决策验证通过。Phase E 已收口，四个无本地卷的 Deployment 可多副本运行，运维手册覆盖环境变量、扩缩容、备份恢复、密钥轮换、时钟与故障处理。ADR-0018 已签字，运行时与开发依赖锁定为带哈希的集合，CI 按锁安装后构建并扫描镜像，SBOM 随构建产出，部署按 digest 引用；两条扫描接受风险带到期日。SLICE-102 把构建后端锁进依赖集合并把 CI action 固定到 commit SHA。ADR-0019 与 SLICE-103/104 让 Postgres 会话表启用并强制 RLS，租户取自已认证 principal，策略由 `sessions enable-rls` 显式安装，运维手册覆盖启用、回滚与排障。ADR-0020 与 SLICE-105/106 把 `app_states` 纳入同一租户边界，`app_name` 带租户前缀，四张表都由 RLS 强制，手册写明旧数据不自动迁移。SLICE-107 让密钥扫描覆盖证据目录并改用已审基线，过期接受风险不再被忽略。SLICE-108 让门禁只读基线，新命中不会被扫描命令写进允许清单。SLICE-109 补齐手动发布流水线与 digest 回写，首次真实推送给操作员执行。SLICE-110 让运行、模型、工具与 A2A 调用以 OTel span 导出，审计 trace_id 与 OTel trace_id 对齐。SLICE-111 让单与顺序计划按步骤落检查点，恢复时跳过已完成步骤，审批等待可恢复。SLICE-112 在模型网关上加了输入输出护栏，PII 脱敏与提示注入阻断，审计只记规则 id 与哈希。SLICE-113 给控制台加了浏览器 OIDC PKCE 登录与三组导航的应用外壳，token 与客户端 secret 不进入浏览器。SLICE-114 把 Runs 与 Plans 的 trace 升级为相对时间瀑布，失败与拒绝分色。SLICE-115 把审批面板做成工作台，截止时间可见、可过滤，并按理由决定。SLICE-116 把 Registry 面板做成卡片，来源、信任、评测与生命周期徽标统一色调，卡片可点击与键盘选中。SLICE-117 让控制台按服务端能力清单显示导航、面板与操作按钮，未知角色回到基础视图，无权深链自动回退。SLICE-118 让审批历史覆盖已决、已过期与已归档记录，文件与 Postgres 语义一致，控制台可按状态过滤。SLICE-119 让 trace 节点带审计字段，瀑布行可点击与键盘选中，Runs 与 Plans 显示 span 详情。SLICE-120 在日志记录工厂层集中转义 CR 与 LF，控制台启动即生效，收敛 CodeQL 的 29 条 log-injection。SLICE-121 增加租户凭据引用绑定，记录只含元数据，引用按租户映射到 `ADK_SECRET_<TENANT>_<NAME>`，控制台与 CLI 可登记、列出与停用，连接器登记要求同租户启用绑定，工具网关按租户作用域取用。SLICE-122 增加连接器自助申请与审批，租户提交申请，管理员批准时重查凭据并登记连接器，文件与 Postgres 单赢家决定，申请与决定写审计。SLICE-123 增加声明式组合器，`single-llm` 模板按参数生成确定性工件，参数只用 `repr` 嵌入，平台密钥签名后走既有评测、注册表与工件存储，组合结果可按 pinned 引用验签加载。SLICE-124 增加定时与 webhook 触发定义，pinned 到 agent 版本，webhook 令牌只存哈希，文件与 Postgres 双存储，CLI 可登记、列出与停用。SLICE-125 增加 webhook 执行服务，`serve-triggers` 按触发令牌哈希认证，pinned 版本验签加载，按租户配额与审计运行，幂等键单赢家，需审批工具的 agent 直接拒绝。SLICE-126 增加共享 `safe_join`，所有文件存储先做路径段白名单校验，再检查解析后的目标仍在存储根目录下。SLICE-127 增加调度循环与重试，schedule 触发按 slot 幂等键单赢家，webhook 与调度共用执行路径，预运行加载失败按次数退避重试，agent 启动后不重试。可做内部试点，未达对外多租户生产标准。

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

每个切片的详细验收、反例和威胁建模在 `docs/specs/SLICE-0xx-*.md`，证据在 `docs/evidence/`。

## 当前验证状态

本机（装了可选驱动）:

- `./.venv/Scripts/python.exe scripts/check.py --fast` -> 1358 passed, 80 skipped，7 步全 PASS
- `./.venv/Scripts/python.exe scripts/check.py --full` -> 9 步全 PASS，1358 passed, 80 skipped（`docs/evidence/SLICE-127-trigger-scheduler.txt`）
- 设置 `TEST_POSTGRES_URL` 后 Postgres 用例可跑；本切片的审批历史用例 4 passed（`docs/evidence/SLICE-118-approval-history.txt`）。完整套件的旧记录为 1236 passed, 1 skipped（`docs/evidence/SLICE-105-app-state-rls.txt`）。
- CI 已在 PR #19 上全绿（run 43708394988），包含锁安装、`--no-build-isolation`、完整门禁、镜像构建、Trivy 扫描与 SBOM 上传。系统 `python` 缺项目依赖，必须用 venv 里的解释器。

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

1. ADR-0001 到 ADR-0024 均已接受。ADR-0003 到 ADR-0006 决定可选依赖不进默认依赖，ADR-0007 新增可选 extra `oidc`（`PyJWT[crypto]`），ADR-0019 决定会话表用 Postgres RLS 做租户隔离，ADR-0020 把 `app_states` 纳入同一边界，ADR-0021 决定 OTel 导出边界，ADR-0022 决定能力驱动的角色视图、声明式组合、自动化与 agent 沙箱顺序，ADR-0023 决定 CodeQL 安全审核通道，ADR-0024 决定 agent 级沙箱的进程隔离、资源上限与出口中介。
2. 本地 venv 为验证装了 `a2a-sdk`、`sqlalchemy`、`asyncpg`、`greenlet`，都不在项目依赖里。换环境要先装。
3. 未跟踪的 `.agents/`、`.claude/agents/`、`.claude/skills/`、`package.json`、`package-lock.json` 是本地工具，不要加进仓库。

## 已知缺口与下一刀建议

已核实的开放项：

1. 发行完整性只剩首次真实发布。release workflow 与回写脚本已合入；操作员设置 registry 凭据、在 `master` 上手动触发，再把 digest 回写 PR。见 `docs/evidence/SLICE-109-release-pipeline.txt`。
2. 密钥扫描不做历史扫描（gitleaks/trufflehog 延后）。GitHub 自定义 pattern 与 validity checks 需要付费套餐，当前关闭。
3. legacy 无前缀 `user_id` 与 plain `app_name` 在 `--session-rls` 开启后不可见，不自动迁移；需要迁移时单独评审。
4. UI 侧的登录、应用外壳、运行详情瀑布、审批工作台、市场卡片、角色视图、审批历史与运行详情下钻已完成，日志注入过滤、租户凭据引用绑定、连接器自助申请、声明式组合器、触发定义、webhook 执行、路径加固、调度循环、执行层级、agent 沙箱 worker、模型出口中介、触发路径的沙箱接入、审批接口、控制台读接口的能力校验与控制台/MCP 的沙箱执行适配、A2A 的注册表启动、沙箱工具调用中介协议与工具执行器接入也已收口（SLICE-113 到 137）。ADR-0024 已确认，下一步是 `in_process` 构建密钥校验与 publish 默认翻转，之后是凭据密钥后端，编号进入时分配。SLICE-110 到 SLICE-137 已完成。
5. 租户凭据只存引用，不存值。密钥后端、KMS、轮换与控制面 `/v1/credentials` 尚未实现；工具网关只做租户作用域，绑定存在性在连接器登记处检查。连接器申请没有过期、通知与控制面接口。组合器只有 `single-llm` 一个模板，没有控制台发布表单，模型通道固定为 LiteLLM allowlist。触发执行已覆盖 webhook 与 schedule，调度按 slot 单赢家且只跑当前 slot，agent 失败不自动重试。文件存储路径已统一走 `safe_join`，Postgres 后端不受影响。执行层级已进 manifest：新发布必须显式声明，无沙箱后端时 `sandboxed` 在发布与加载两处被拒；历史记录缺字段按 `in_process` 读取且 digest 不变。组合器与脚手架当前明确写 `in_process`，手写 manifest 暂无法与平台产物区分；SLICE-129 已交付子进程 worker 与协议，但尚未注册后端，publish 仍默认不可用；接入切片把 publish 默认翻成 `sandboxed`，`in_process` 只接受平台构建密钥签名的工件。沙箱 worker 的残余风险：POSIX 上 RLIMIT_NPROC 按 uid 计数且默认关闭，工件仍可读宿主文件系统，Windows 只有脚本级守卫；网络守卫是 Python 层，内省拿原始 C 类型或用 ctypes 可绕过。模型调用已经经父进程中转，工具调用仍被守卫拒绝，工具网关 RPC 留给接入切片；接入切片还必须同时落地平台门槛（POSIX、降 uid、网络命名空间）、`sandboxed` 的执行路由与平台构建密钥校验，再允许注册后端。这些按 ADR-0022 与 ADR-0024 的顺序另行切片。

6. 控制台的读路径已在 SLICE-133 对齐到面板能力（审计、策略、注册表与评测、工具、工具授权、连接器与申请、凭据、对端与远程目录）。仍只做认证加租户/admin 判断的是写路径与基础能力接口：注册表 load/unload、connectors 注册/停用/检查、connector-requests 提交与决定、credentials 注册/停用、peers 与远程 agent 的写操作、tool-grants 提交与决定、`/api/runs`、`/api/plans`、`/api/traces/{id}`、`/api/sessions`、`/api/chat`（后五个按基础能力 `runs.read`、`sessions.read`、`chat.run`）。写路径的能力对齐与 `grants.decide`、`connectors.manage` 的界面服务端不一致（界面给 operator 显示决定按钮但服务端仅 admin）另行切片。审批历史查询参数 `limit` 由 FastAPI 在进入处理函数前转换，越权调用方带非整数 `limit` 会先得 422 而非 403；不泄露数据，记为已知小缺口。

其余方向从 `docs/specs/ROADMAP.md` 的里程碑状态里选。

MCP 和 A2A 路径都已经通过 `AuditedRunner` 补上 `agent.run` 审计和配额。A2A 消费方的出站调用由 `a2a_egress.AuditTransport` 审计，见 SLICE-095。A2A 的 executor 用 `isinstance(runner, Runner)` 检查，代理靠 `__class__` property 通过，升级 ADK 时要复核。

配额表启用了 Postgres RLS，策略依赖 `app.tenant_id`。生产连接必须是表的属主，不能用超级用户或 `BYPASSRLS` 角色，否则策略不生效。建表步骤会自动 `ENABLE` 和 `FORCE`，连接角色没有 `ALTER TABLE` 权限时启动会失败。

## 恢复步骤

1. 读 `CLAUDE.md`、`docs/specs/ROADMAP.md`、本文件。
2. 跑 `python scripts/check.py --fast` 确认基线。
3. 从上面“下一刀建议”或 ROADMAP 候选里挑一个，先写 `docs/specs/SLICE-xxx.md`，先红后绿。
