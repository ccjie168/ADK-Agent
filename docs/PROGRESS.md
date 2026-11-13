# 项目进度登记

更新日期: 2026-11-13
分支: master
最新提交: 待填（SLICE-063 控制台接共享审计）
状态: 可交接暂停，工作区干净（只留本地工具目录未跟踪）

## 一句话

企业级 ADK agent 平台的 M0 到 M5 已全部收口，另加控制台可见性、审计客户端接入、只读运营视图、OIDC 解析器、控制台 OIDC 接线、服务面 OIDC 接线、MCP HTTP 认证、MCP principal 注入、共享配额、审批收件箱、MCP 运行审计、指标与 trace、A2A 运行审计、审批过期、服务指标端点、审批归档、配额行级隔离、审计轮转签名、模型熔断、文件状态备份恢复、压测基线、SSE 有界缓冲、入口限流、MCP/A2A 限流、审计密钥轮换、可选的会话租户隔离和审计只读查询和控制台共享审计二十八个切片。本地门禁全绿。OIDC 身份链路完整，多副本配额在 Postgres 上共享并由 RLS 约束，审批可以跨进程走通并有截止时间和归档，MCP 和 A2A 调用都有审计和配额，控制台、两个网关和 MCP 都有 Prometheus 指标，trace 能跨边界传播，审计链支持分段和 HMAC 验签，模型 provider 有熔断，注册表和审计可以打包备份并安全恢复，配额与审计吞吐有可复现的压测基线，控制台 SSE 在慢客户端下内存有界且会报告丢弃数，控制台、三个独立服务、MCP 和 A2A 都按调用方限流，审计签名密钥可轮换而不作废旧记录，会话可以按租户隔离，审计服务可按租户查询事件，控制台的审计与运行面板读同一份共享数据。可做内部试点，未达对外多租户生产标准。

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
| SLICE-063 | 控制台接共享审计 | 待填 |

每个切片的详细验收、反例和威胁建模在 `docs/specs/SLICE-0xx-*.md`，证据在 `docs/evidence/`。

## 当前验证状态

本机（装了可选驱动）:

- `./.venv/Scripts/python.exe scripts/check.py --fast` -> 739 passed, 13 skipped，7 步全 PASS
- `./.venv/Scripts/python.exe scripts/check.py --full` -> 739 passed, 13 skipped，9 步全 PASS
- 本轮未推送，CI 未运行。系统 `python` 缺项目依赖，必须用 venv 里的解释器。

13 个 skip 是：7 条 Postgres 配额用例、4 条 RLS 用例、1 条 Postgres 会话用例（都需 `TEST_POSTGRES_URL`）、以及 `RLIMIT_AS` 仅 POSIX 的平台跳过。设 `TEST_POSTGRES_URL` 后 11 条配额和 RLS 用例会跑，本地 `postgres:15-alpine` 已验证全过。CI 不装 `a2a-sdk`，另有 4 条 A2A 用例按条件跳过。

## 怎么跑

```bash
# 唯一门禁
python scripts/check.py --fast
python scripts/check.py --full

# 控制台（本地开发）
python -m adk_agent console --agents examples/minimal/agent.py \
  --host 127.0.0.1 --port 8081 --allow-unauthenticated

# 控制台带共享配额（多副本时 QUOTA_URL 指向同一个库）
QUOTA_URL=postgresql://postgres:adk@127.0.0.1:5432/adk \
  python -m adk_agent console --agents examples/minimal/agent.py \
  --quota-config quota.json

# 控制台带审批收件箱，执行器和控制台共用同一个目录
python -m adk_agent console --agents examples/minimal/agent.py \
  --approval-dir ./approvals --approval-ttl 3600

# MCP 服务带审计、配额和指标
QUOTA_URL=postgresql://postgres:adk@127.0.0.1:5432/adk \
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
python scripts/loadtest.py quota --requests 2000 --concurrency 32 --max-runs 1000 \n  --url postgresql://postgres:adk@127.0.0.1:55432/adk
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

1. ADR-0003 到 ADR-0007 已于 2026-11-12 接受。ADR-0003 到 ADR-0006 都决定可选依赖不进默认依赖。ADR-0007 新增可选 extra `oidc`，内容是 `PyJWT[crypto]`。
2. 本地 venv 为验证装了 `a2a-sdk`、`sqlalchemy`、`asyncpg`、`greenlet`，都不在项目依赖里。换环境要先装。
3. 未跟踪的 `.agents/`、`.claude/agents/`、`.claude/skills/`、`package.json`、`package-lock.json` 是本地工具，不要加进仓库。

## 已知缺口与下一刀建议

按优先级：

1. ADR-0008 工件与插件化加载：工件抽象成 store/loader 端口，第一版进程内加载，是市场与按 digest 运行的前提。
2. 注册表 Postgres 后端（Phase B2）：元数据与 manifest 先入库，保留 `AgentRegistry` 端口，文件实现降级。
3. 跨副本共享限流计数。需要 Redis 或入口网关，属于新依赖，先出 ADR。
2. Inbound 请求限流。目前只有运行配额和 provider 熔断，入口层限流仍留给网关或反向代理。
3. ADK 会话表的行级隔离。它的查询由 ADK 生成，无法注入 `app.tenant_id`，目前只按 subject 隔离。
4. 审计签名的密钥轮换。换密钥后旧记录不能用新密钥验证。

MCP 和 A2A 路径都已经通过 `AuditedRunner` 补上 `agent.run` 审计和配额。A2A 的消费方 `RemoteA2aAgent` 仍在本进程外，没有审计。A2A 的 executor 用 `isinstance(runner, Runner)` 检查，代理靠 `__class__` property 通过，升级 ADK 时要复核。

配额表启用了 Postgres RLS，策略依赖 `app.tenant_id`。生产连接必须是表的属主，不能用超级用户或 `BYPASSRLS` 角色，否则策略不生效。建表步骤会自动 `ENABLE` 和 `FORCE`，连接角色没有 `ALTER TABLE` 权限时启动会失败。

## 恢复步骤

1. 读 `CLAUDE.md`、`docs/specs/ROADMAP.md`、本文件。
2. 跑 `python scripts/check.py --fast` 确认基线。
3. 从上面“下一刀建议”或 ROADMAP 候选里挑一个，先写 `docs/specs/SLICE-xxx.md`，先红后绿。
