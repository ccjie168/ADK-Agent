# 运维手册：多副本部署

适用版本: SLICE-100。示例清单在 `deploy/k8s/multi-replica.yaml`，单机示例在 `deploy/k8s/deployment.yaml` 与 `docker-compose.yml`。本手册不覆盖托管数据库的供给、TLS 终止和服务网格。

前提：

- PostgreSQL 15 或更新，所有共享状态在同一个库或同一组库。
- Redis 7 或更新，只用于限流计数，可丢。
- Kubernetes 1.28 或更新；镜像由现有 `Dockerfile` 构建。
- 所有节点与数据库做 NTP 对时。

## 拓扑

| 工作负载 | 副本 | 对外 | 本地状态 |
| --- | --- | --- | --- |
| `adk-console` | 3 | Service `adk-console:80` | 无 |
| `adk-mcp` | 3 | Service `adk-mcp:80` | 无 |
| `adk-audit` | 2 | Service `adk-audit:80` | 无 |
| `adk-registry` | 2 | Service `adk-registry:80` | 无 |

共享状态：

| 变量 | 存储 | 内容 |
| --- | --- | --- |
| `SESSION_URL` | Postgres | ADK 会话，必须 `postgresql+asyncpg://` 或 `memory://` |
| `REGISTRY_DATABASE_URL` | Postgres | 发布版本、生命周期、评测报告、连接器 |
| `ARTIFACT_URL` | Postgres | 工件字节；与注册表可同库 |
| `GRANT_URL` | Postgres | 工具临时授权 |
| `AUDIT_DATABASE_URL` | Postgres | 每租户审计哈希链 |
| `APPROVAL_DATABASE_URL` | Postgres | 审批请求与决定 |
| `QUOTA_URL` | Postgres | 配额计数与并发租约 |
| `RATE_LIMIT_URL` | Redis | 跨副本固定窗口计数 |

文件后端（目录收件箱、JSONL 审计、文件注册表、`SESSION_DB`）只用于单机或演示。多副本下任何一个文件后端都会让副本看到不同状态，清单里禁止 PVC 与 `SESSION_DB`。

## 环境变量

除 `PORT`、`ADK_AGENT_MODEL`、`ANTHROPIC_BASE_URL` 这类非敏感值外，所有 DSN、token、密钥环都从 Secret `adk-agent-secrets` 用 `secretKeyRef` 注入。示例键名见 `deploy/k8s/secret.example.yaml`。

| 变量 | console | mcp | audit | registry |
| --- | --- | --- | --- | --- |
| `SESSION_URL` | 是 | 是 | 否 | 否 |
| `AUDIT_DATABASE_URL` | 是 | 是 | 是 | 是 |
| `APPROVAL_DATABASE_URL` | 是 | 否 | 否 | 否 |
| `GRANT_URL` | 是 | 否 | 否 | 否 |
| `QUOTA_URL` | 是 | 是 | 否 | 否 |
| `RATE_LIMIT_URL` | 是 | 是 | 是 | 是 |
| `REGISTRY_DATABASE_URL` | 否 | 否 | 否 | 是 |
| `ARTIFACT_URL` | 否 | 否 | 否 | 是 |
| `ADK_AUDIT_KEYRING` | 是 | 是 | 是 | 是 |
| `ADK_ARTIFACT_KEYS` | 否 | 否 | 否 | 是 |
| `ADK_MCP_AUTH_TOKEN` | 是 | 是 | 是 | 是 |

限流必须同时给 `--rate-limit`；只设 `RATE_LIMIT_URL` 不会开启限流。示例命令已带 `--rate-limit 120 --rate-limit-window 60`，审计与注册表用 240。

生产环境建议用 OIDC 替代共享 Bearer token：各服务加 `--oidc-config`，控制台去掉 `--role admin`，授权由 token 的租户与角色决定。共享 token 只适合演示与内网。

控制台的浏览器登录需要在同一配置文件加 `browser` 段。`redirect_uri` 必须与控制台的真实地址一致，回调路径固定为 `/auth/callback`：

```json
{
  "issuer": "https://idp.example.com",
  "audience": "adk-console",
  "jwks_url": "https://idp.example.com/jwks",
  "browser": {
    "client_id": "adk-console",
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "redirect_uri": "https://adk.example.com/auth/callback",
    "scopes": ["openid", "profile", "email"]
  }
}
```

浏览器只拿到授权端点、client id 与回调地址；`token_endpoint` 和 `client_secret_env` 留在服务端。机密客户端把 `client_secret_env` 指向环境变量名，不要写明文。没有 `browser` 段时控制台仍可用手工 Bearer token 登录。

## 首次部署

1. 建库建角色。配额表的行级安全要求应用角色拥有表且不是 superuser、没有 `BYPASSRLS`，否则策略被绕过。审计与审批 v1 没有 RLS，靠服务层过滤。
2. 起 Redis。限流计数可丢，不需要持久化。
3. 写 Secret。推荐 `kubectl create secret generic adk-agent-secrets --from-literal=...` 或外部密钥管理，不要提交真实值。审计密钥环是 JSON，所有写审计的进程必须用同一份。
4. `kubectl apply -f deploy/k8s/multi-replica.yaml`，等四个 Deployment 就绪。表结构在首次使用时用 `CREATE TABLE IF NOT EXISTS` 自动创建，没有独立迁移工具；滚动升级只做加法，破坏性变更需要单独迁移评审。
5. 用 `adk-agent publish` 向注册表发布一个版本，再让控制台用 `--registry-url` 指向 `adk-registry`。控制台示例命令用镜像内的 minimal agent；生产用 `--agent-ref` 从注册表加载。
6. 冒烟：四个 `/healthz` 返回 200；控制台能列版本与工具；审批接口在 `APPROVAL_DATABASE_URL` 设置后可用；`adk-agent verify-audit --audit-db "$AUDIT_DATABASE_URL"` 通过。
7. Service 默认 ClusterIP。需要外部访问时在入口层做 TLS 与认证，不要直接暴露未鉴权端口。

## 发行与升级

- 依赖锁由 `pip-tools` 生成，不要手改。两个文件都在 `requirements/`，全部 `==` 且带哈希。重新生成：

  ```bash
  docker run --rm -v "$PWD:/w" -w /w python:3.13-slim bash -lc '
    pip install --quiet "pip-tools>=7.4" && mkdir -p requirements &&
    pip-compile --generate-hashes --no-emit-index-url --no-emit-trusted-host \
      --output-file requirements/runtime.lock \
      --extra build --extra claude --extra litellm --extra http --extra oidc --extra publish --extra redis --extra otel pyproject.toml &&
    pip-compile --allow-unsafe --generate-hashes --no-emit-index-url --no-emit-trusted-host \
      --output-file requirements/dev.lock \
      --extra dev --extra build --extra claude --extra litellm --extra http --extra oidc --extra publish --extra redis --extra otel pyproject.toml
  '
  ```

  改 `pyproject.toml` 后必须重编两个锁，diff 和代码一起评审。不要在镜像或 CI 里用范围安装。
- dev 锁用 `--allow-unsafe`，把 `pip` 与 `setuptools` 固定下来。`pip-tools` 依赖未固定的 `setuptools`，CI 用 `--require-hashes` 安装时必须有这个 pin。
- 默认镜像包含 `litellm`，因为未设置 `ADK_AGENT_MODEL` 时模型默认回退到 LiteLLM 的 `deepseek/deepseek-v4-pro`。国内模型用 `litellm:deepseek/<model>`，凭据放在 Secret 的 `DEEPSEEK_API_KEY`（或 LiteLLM 对应的 provider 变量）。也可以继续用清单里的 Anthropic 兼容端点。
- CI 按 `dev.lock` 安装后跑门禁，构建镜像，Trivy 扫描 `HIGH,CRITICAL` 可修复项，并上传 SBOM。扫描失败不得合入。
- 发布走 `.github/workflows/release.yml`，手动触发，只在 `master` 上运行。输入 `image` 填自建 registry 的完整引用且不带 tag，例如 `registry.local:5000/adk/adk-agent`；自建 registry 只能内网访问时，`runner` 填能连到它的自托管 runner 标签。凭据用仓库 secret `REGISTRY_USERNAME` 与 `REGISTRY_PASSWORD`。workflow 先跑完整门禁与 Trivy，扫描通过才推送，digest 写进 `release.txt` 与 run summary。
- 推送成功后本地执行 `python scripts/release_digest.py --image <image> --digest <digest>`，脚本只改两个清单里的 digest 行，再按正常 PR 评审合并。脚本拒绝带 tag、带 digest 或没有 registry 前缀的镜像引用，也拒绝格式不对的 digest。
- `image:` 只接受 `<registry>/<path>@sha256:<digest>`，不接受 `:latest` 或可移动标签。自建 registry 建议用 HTTPS；用 HTTP 内网 registry 时，runner 的 Docker daemon 要显式把它加入 insecure registries。
- 受限网络构建时可传 `--build-arg PIP_INDEX_URL=<mirror>` 与 `--build-arg APT_MIRROR=<debian mirror>`。这两个 arg 都不写进镜像；锁里的哈希仍然校验下载的包。
- 镜像构建会把基础镜像里的 `zlib1g` 升到当前安全版本。基础镜像快照早于该更新，不升级就会被 Trivy 拦下。
- 扫描的接受风险写在 `.trivyignore.yaml`，每条必须有 `statement` 与 `expired_at`。到期后 Trivy 会重新报出，必须修复或重新评审后延期。当前两条：`filelock` 受 litellm 与 ADK 的版本上限约束无法升级，`setuptools` 只存在于基础镜像被删除的层里，合并后的文件系统没有它。
- 基础镜像的 digest 写在 `Dockerfile` 的 `ARG PYTHON_IMAGE` 里。升级基础镜像是显式提交，重新构建、重新扫描、重新跑门禁。
- 回滚用上一个 digest 重新 apply，不重建镜像。数据库 schema 只做加法，旧镜像可以在新表结构上运行；破坏性变更必须单独评审。
- `gemini` 不在默认镜像里。需要时另建带该 extra 的镜像和锁，不要在生产镜像里临时 `pip install`。

## 会话存储的租户隔离（ADR-0019、ADR-0020）

`--session-rls` 把会话表的租户隔离交给 Postgres RLS。默认关闭，只在 `SESSION_URL` 是 Postgres 且 `--session-tenant-scope` 打开时可用。范围是 `sessions`、`events`、`user_states`、`app_states` 四张表。

启用顺序：

1. 确认 `SESSION_URL` 指向共享 Postgres。应用角色要能建表。
2. 启动一次 console 或 serve，创建一个会话，让 ADK 建出 `sessions`、`events`、`user_states`、`app_states`。没有表时 `enable-rls` 退出 1 并提示。
3. 用这四张表的属主角色运行 `adk-agent sessions enable-rls --database-url "$SESSION_URL"`，预期输出 `session rls enabled`。命令幂等，可以重跑。
4. 重启服务并加 `--session-tenant-scope --session-rls`。启动检查会看四张表的 `relrowsecurity`、`relforcerowsecurity` 和策略；缺失时退出 1。
5. 用两个不同租户的 token 各开一次会话，确认 `/api/sessions` 互不可见。
6. 决定旧数据。开启后 `user_id` 与 `app_name` 都带租户前缀，旧的 plain `app_name` 会话与 `app_states` 都读不到。生产环境要先迁移或明确接受丢弃。

角色要求：

- 应用角色必须是四张表的属主，不能是 superuser，不能有 `BYPASSRLS`。superuser 永远绕过 RLS，用它验证会得到假阳性。
- 策略安装与运行时用同一角色。换角色后先 `ALTER TABLE ... OWNER TO ...`，再重跑 `enable-rls`。

行为：

- 租户取自已认证 principal，不取 `user_id` 或 `app_name`。传别的租户的 `user_id` 读到 0 行。
- 运行外的会话调用由控制台与 MCP 设置请求上下文；运行路径用 invocation principal。
- 开启后会话服务看到的 `app_name` 是 `<tenant>:<agent>`。`app_states` 按这个前缀隔离，控制台、MCP、审计与 manifest 里的 agent 名不变。
- 没有冒号前缀的 legacy `user_id` 与没有租户前缀的 `app_name` 在开启后不可见，不自动迁移。

回滚：

1. 去掉 `--session-rls` 重启服务。表与策略保持原样，只是不再强制。
2. 需要彻底移除策略时，用属主执行 `ALTER TABLE <t> DISABLE ROW LEVEL SECURITY` 和 `DROP POLICY <t>_tenant ON <t>`。这会降低隔离，按破坏性变更评审。
3. 不要用 `DROP TABLE` 回滚，会丢会话数据。

排障：

- 启动报 `session table ... does not enforce RLS`：策略没装或表被重建。重跑 `sessions enable-rls`。
- 会话列表为空：检查 token 的 tenant、`user_id` 前缀与 `app_name` 前缀是否一致，以及 `--session-tenant-scope` 是否打开。
- 应用级状态读不到：确认写入方的 `app_name` 带当前租户前缀，且写入方与读取方用同一租户 token。
- 安装策略报权限错误：当前角色不是表属主，或表是由别的角色建的。换属主角色再跑。

## 模型护栏

- `serve-model-gateway --guardrails <file>` 加载 JSON 规则；不传则关闭，行为与之前一致。
- 内置规则覆盖邮箱、手机号、身份证号的脱敏，以及中英文提示注入的阻断。规则可以只对 `input`、只对 `output` 或两者生效。
- 命中阻断时返回 403 `model_denied`，provider 不会被调用；命中脱敏时请求或响应里的原文被替换为 `[redacted]`。
- 每次拦截或脱敏写 `guardrail.input` / `guardrail.output` 审计，只记规则 id 与原文哈希，不记原文。
- 正则非法或配置文件不合法时服务拒绝启动。规则文件不要写真实密钥或 DSN。

## RAG 向量存储（pgvector，ADR-0035）

向量库与平台库共用同一个 Postgres。数据在 `adk_rag_chunks` 表里，主键 `(tenant, source_id, chunk_id)`，列包括 `body`、`embedding vector(N)`、`data_classes text[]` 与 `allowed_subjects text[]`。

安装与建表：

1. 在承载 `adk_rag_chunks` 的库里一次性安装 pgvector 扩展。pgvector 不是受信扩展，建它需要 superuser 或 DBA。`PgVectorRagStore` 首次连接会执行 `CREATE EXTENSION IF NOT EXISTS vector`；扩展已存在时该语句只发 NOTICE 后跳过，不再检查建扩展权限，所以应用角色本身不需要这项权限，但由它首连安装时就需要。
2. 同一段 schema 还会建表并安装策略。首次启动后确认三件事：`SELECT extversion FROM pg_extension WHERE extname = 'vector';` 有值、`\d adk_rag_chunks` 的 `embedding` 是 `vector(N)`、`pg_class.relrowsecurity` 与 `relforcerowsecurity` 都为真。
3. 生产环境可以由 DBA 预建扩展与表，但应用角色必须是 `adk_rag_chunks` 的属主，不能只给 DML。每个进程首次建立连接池时都会重跑这段 schema，其中的 `CREATE TABLE IF NOT EXISTS`、`ENABLE/FORCE ROW LEVEL SECURITY`、`DROP POLICY` 与 `CREATE POLICY` 需要表属主权限。只给 DML 的角色首连就失败，异常被包成 `RagStoreUnavailable`。另外 `CREATE TABLE IF NOT EXISTS` 即使表已存在，也会先检查 schema 上的 `CREATE` 权限，所以应用角色还要对建表所在的 schema 有 `CREATE`，或者直接拥有该 schema。生产上先由 superuser/DBA 装好扩展，再把 `adk_rag_chunks` 的属主与 schema 权限授予应用角色。

租户隔离：

- 表启用并强制 RLS，策略 `adk_rag_chunks_tenant` 的判定是 `tenant = current_setting('app.tenant_id', true)`。每次 upsert 与检索都在事务里先 `SET LOCAL` 等价的 `set_config`，事务结束即失效，不会漏到池里的下一条连接。
- 应用角色必须是表的属主，不能是 superuser，不能有 `BYPASSRLS`。superuser 永远绕过 RLS，用它验证会得到假阳性。
- 不要为了排障临时 `DISABLE ROW LEVEL SECURITY`。检索路径不提供无 ACL 的降级分支。

维度与重建索引：

- `PgVectorRagStore(url, dimensions=N)` 的 `N` 必须等于 embedding 模型输出的维度。维度不符时写入与检索都抛 `RagStoreUnavailable`，见下节。
- `vector(N)` 的维度写在列定义里，改维度不是改参数，而是要重建：新建列或新表（例如 `embedding_v2 vector(M)`）、按新模型重新摄取全部来源、校验行数、再切换读取方，最后删除旧列。不要原地 `ALTER` 旧列后继续用旧向量。
- 摄取与检索必须用同一 `provider`/`model`。换 embedding 模型等于换向量空间，新旧向量不能混在同一列里比较。

索引与重建：

- schema 只建表与策略，不自动建 ANN 索引，检索是租户内全量 `<=>` 排序。行数到十万级前这么做可以接受；更大时手工建索引：

  ```sql
  CREATE INDEX IF NOT EXISTS adk_rag_chunks_embedding
      ON adk_rag_chunks USING hnsw (embedding vector_cosine_ops);
  ```

- `hnsw` 对 `vector` 类型上限 2000 维，超过要先降维或改用 `halfvec`。建索引后跑一次 `ANALYZE adk_rag_chunks`。
- 批量重新摄取或删掉大量来源后，索引会膨胀。低峰时执行 `REINDEX INDEX CONCURRENTLY adk_rag_chunks_embedding;`，不要用阻塞式的 `REINDEX`。

失败模式（fail-closed）：

- 扩展缺失、维度不符、驱动或 SQL 报错都统一抛 `RagStoreUnavailable`。调用方拿到的是异常，不是空引用列表，检索不会退化成无 ACL 的路径。
- 空结果与故障要分开处理：空列表表示没有问题匹配 ACL 的文档，`RagStoreUnavailable` 表示存储不可用。告警只看后者。
- 配置了 `RagGuard` 时，低置信度与提示注入的引用在返回前被过滤掉，不会出现在结果里。没配置就不过滤，生产环境应配置。

多副本：

- 向量与索引都在共享 Postgres 里，副本无本地状态。同一事务提交后其他副本立即可见，不需要副本间同步或预热。
- 扩容前确认所有副本指向同一个库。指错库的副本只会查到自己的数据，表现为部分租户检索为空，不是报错。
- 每个副本首次连上时都会执行同一段 schema。语句本身幂等，但多个副本同时首启时 Postgres 的 `CREATE EXTENSION IF NOT EXISTS` 与 `CREATE TABLE IF NOT EXISTS` 仍可能撞唯一索引而报错，该副本的首次请求会失败并抛 `RagStoreUnavailable`。重试即恢复，数据不会损坏。要求首启零失败就用 DBA 先建好扩展与表，再滚动副本。
- `adk_rag_chunks` 与其它 `adk_*` 表一起进 `pg_dump`，备份与恢复顺序同「备份与恢复」一节。
- `adk-agent rag ingest` 与 `adk-agent rag search` 是手工装料与自检入口，参数见 `docs/contracts/cli.md`。

### 运行时检索（ADR-0036）

- `console` 与 `serve-triggers` 接受 `--rag-db URL`、`--rag-dimensions N`、`--rag-model MODEL`、
  `--rag-provider NAME`（默认 `litellm`）。不给 `--rag-db` 完全不启用；给了但缺维度或模型退出 1。
- 只有 manifest 里 `rag.enabled=true` 的 agent 会检索。控制台用 `--agents` 文件加载的 agent 没有
  manifest，永远不启用；按需加载的注册表记录按自己的配置生效。触发服务按 pinned 记录生效。
- 检索在调模型前做一次，结果拼在用户消息最前面；`top_k`、`min_confidence`、`data_classes` 全部来自
  manifest。查询嵌入写 `model.embed` 审计，每次检索写一条 `rag.retrieve`（计数、状态、延迟，不含
  查询与片段）。
- 失败语义：`rag.on_error=deny`（默认）让本次运行失败；`degrade` 记审计后不带上下文继续，是显式的
  风险接受，审计里能看到 `status=error`。
- 现状与缺口：`--budget-usd` 与嵌入预算都是进程内累计，多副本各自记账；`execution_tier=sandboxed` 的
  触发在 `serve-triggers` 里提前返回，不会检索，也没有 `rag.retrieve` 审计；MCP 与 A2A 入口尚未接线；
  `--rag-dimensions` 给 0 会以未捕获的 `RagStoreUnavailable` 退出，运维不要这么配。
- 升级顺序：先装扩展与表，再给控制台或触发加 `--rag-*` 重启，最后把 agent 的 manifest 改成
  `rag.enabled=true` 重新发布。回滚时把 manifest 关掉即可，表可以留着。

## 扩缩容

- 扩副本前逐项确认上表里的共享后端都已设置。任一文件后端仍在用时禁止扩容。
- 审计写入在租户内由 advisory lock 串行化。副本数增加的是读取与其它租户的并行度，单租户写入吞吐不会随副本线性增长。扩缩容前用 `scripts/loadtest.py` 复测。
- 审批等待是轮询。副本多、待办多时提高轮询开销；按 `--approval-ttl` 与 `poll_seconds` 设预期延迟。
- 跨副本限流依赖 `RATE_LIMIT_URL`。Redis 故障时回退到每进程限流，配额不跨副本，属于已知降级。
- 控制台的 `--max-loaded-agents` 决定每副本内存上限，扩容不改变单副本上限。

## 备份与恢复

- `pg_dump` 覆盖所有 `adk_*` 表与会话表；工件字节若在 `ARTIFACT_URL` 指向的库内，同一份 dump 带走。对象存储另行备份。
- Redis 不需要备份，恢复后限流窗口从零开始。
- 恢复后先 `adk-agent verify-audit --audit-db "$AUDIT_DATABASE_URL"`。验签失败说明密钥环不匹配或数据被改，不要带病上线。
- 审批归档用 `adk-agent approvals prune --db "$APPROVAL_DATABASE_URL" --older-than SECONDS`；审批表与归档表都要在备份范围内。
- 工件验签公钥（`ADK_ARTIFACT_KEYS`）和审计密钥环要单独备份，否则备份无法验证。
- 恢复顺序：数据库就绪、Secret 就绪、再滚动 Pod。Pod 无本地状态，重建不丢数据。

## 密钥轮换

- **审计签名**：`ADK_AUDIT_KEYRING` 支持 `active`、`keys`、`legacy`。轮换是加法：新 key 加入 `keys` 并设为 `active`，旧 key 留在 `keys`（无 kid 的旧记录用 `legacy`）。删掉历史用过的 key 会让整链验证在该记录处失败。更新 Secret 后滚动所有写审计的进程。
- **Bearer token**：共享 token 轮换需要客户端同步换值，做不到零停机。需要零停机就用 OIDC。
- **工件验签**：新增 key id 并发布新版本，旧公钥保留到所有旧版本退役。
- **数据库口令**：在 Postgres 改角色口令，更新 Secret，滚动重启。连接池会重连。
- **凭据数据密钥（Vault Transit，ADR-0027）**：应用令牌只需要 `transit/encrypt|decrypt|rewrap/<key>`
  的 `update` 权限；轮换执行 `vault write -f transit/keys/<key>/rotate`，再对各租户跑
  `credentials rewrap`。不要删除旧版本密钥，除非确认所有记录都已 rewrap；低于
  `min_decryption_version` 的旧记录会 fail-closed。Vault 不可达时凭据解析返回
  `secret_unavailable`，控制面 503，不回退本地 KEK，按 fail-closed 处理并恢复 Vault。

凭据密钥后端相关变量：`ADK_SECRET_BACKEND`（`local`|`vault`）、`ADK_VAULT_ADDR`、
`ADK_VAULT_KEY`、`ADK_VAULT_TOKEN_FILE` 或 `ADK_VAULT_TOKEN`、`ADK_VAULT_TRANSIT_MOUNT`、
`ADK_VAULT_NAMESPACE`、`ADK_VAULT_CACERT`、`ADK_VAULT_TIMEOUT`。vault 模式与
`ADK_SECRET_KEKS`/`ADK_SECRET_KEKS_FILE` 互斥；令牌文件在 POSIX 上不得被组或其他用户读取。

## 时钟

- 审批与审计的过期判断用数据库的 `now()`，不是进程时钟。本机实测主机时钟曾比 Postgres 容器快约 4 秒。
- 节点与数据库都必须做 NTP。审批截止时间要远大于时钟偏差；不要把 TTL 设成几秒。
- 审计记录的时间戳由写入进程生成，跨主机排查按 trace id 关联，不依赖时间先后。

## 故障模式

| 故障 | 表现 | 处理 |
| --- | --- | --- |
| Postgres 不可达 | 审批接口 503 `approval_unavailable`；注册表与配额请求失败；审计写入失败 | 恢复数据库，Pod 自动重连；不要切回文件模式 |
| Vault 不可达或令牌过期 | 凭据解析 `secret_unavailable`；控制面 503；`rewrap` 退出 1 | 恢复 Vault 或续令牌；不要切回本地 KEK，旧记录会 fail-closed |
| Redis 不可达 | 限流回退到每进程计数 | 容量按单副本上限估算，恢复后自动回到共享计数 |
| `SESSION_URL` 误设为 `memory://` | 会话在副本间不共享 | 改成 Postgres DSN 并滚动 |
| 会话 RLS 策略缺失 | 带 `--session-rls` 启动退出 1，提示 `sessions enable-rls` | 以属主角色重跑命令，再重启 |
| 某个写方审计密钥环不同 | `verify-audit` 在该租户该序号失败 | 统一 Secret 后滚动全部写方，不要重签历史 |
| 审批长时间无人处理 | 请求到期后从待办消失，执行器收到超时 | 提高值守频率或缩短 TTL；归档用 prune |
| 审计写吞吐成为瓶颈 | 单租户写入排队 | 按租户分流或提高单租户上限；先压测再改 |
| 模型 provider 故障 | 熔断打开，返回 `ModelUnavailable` | 等熔断半开或切换 provider 配置 |
| 节点驱逐 | Pod 重建，无数据丢失 | PDB 保住控制台至少 2 副本 |

## 值守检查

- 四个 Service 的 `/healthz` 与受保护的 `/metrics`。抓取账号要绕过限流或使用独立 token。
- 审批待办数量与最老待办年龄：`GET /api/approvals`。到期请求不会出现在列表里，积压看审计的 `approval.request` 事件。
- 审计链每日验证一次：`verify-audit --audit-db`。失败按租户与序号定位。
- Postgres：连接数、advisory lock 等待、`adk_audit_records` 与 `adk_approvals` 的增长、WAL 与磁盘。
- Redis：内存与淘汰；淘汰只影响限流精度。
- 日志与指标不得出现 token、DSN 或待审 `input`。发现即按泄露处理并轮换。
- OTel 默认关闭。设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 后导出 `agent.run`、`model.call`、`tool.call` 与 `a2a.call`，属性只含租户、run、agent、模型、token 用量与成本，不含 prompt、completion 或工具参数原文。导出失败只告警一次，不影响运行；审计链继续是权威记录。
- 公开仓库已启用 GitHub secret scanning、push protection 与 Dependabot security updates。自定义 pattern 与 validity checks 需要付费套餐，当前关闭。仓库根的 `.secrets.baseline` 是 detect-secrets 的已审基线；门禁只读它、不改写，新命中会让门禁失败。更新基线必须单独提交并评审。已接受漏洞的到期由 `.trivyignore.yaml` 的 `expired_at` 控制，`check.py` 与 `sbom.py` 会停止忽略过期项。
- 滚动升级前跑一次 `python scripts/check.py --full`，升级后重跑冒烟与验签。
