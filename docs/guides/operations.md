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
    pip-compile --generate-hashes --output-file requirements/runtime.lock \
      --extra claude --extra litellm --extra http --extra oidc --extra publish --extra redis pyproject.toml &&
    pip-compile --generate-hashes --output-file requirements/dev.lock \
      --extra dev --extra claude --extra litellm --extra http --extra oidc --extra publish --extra redis pyproject.toml
  '
  ```

  改 `pyproject.toml` 后必须重编两个锁，diff 和代码一起评审。不要在镜像或 CI 里用范围安装。
- 默认镜像包含 `litellm`，因为未设置 `ADK_AGENT_MODEL` 时模型默认回退到 LiteLLM 的 `deepseek/deepseek-v4-pro`。国内模型用 `litellm:deepseek/<model>`，凭据放在 Secret 的 `DEEPSEEK_API_KEY`（或 LiteLLM 对应的 provider 变量）。也可以继续用清单里的 Anthropic 兼容端点。
- CI 按 `dev.lock` 安装后跑门禁，构建镜像，Trivy 扫描 `HIGH,CRITICAL` 可修复项，并上传 SBOM。扫描失败不得合入。
- 发布时先推送镜像，取得 digest，再替换清单里的全零 digest。`image:` 只接受 `adk-agent@sha256:<digest>`，不接受 `:latest` 或可移动标签。取 digest 可用 `docker buildx imagetools inspect <image>` 或 `crane digest <image>`。
- 受限网络构建时可传 `--build-arg PIP_INDEX_URL=<mirror>` 与 `--build-arg APT_MIRROR=<debian mirror>`。这两个 arg 都不写进镜像；锁里的哈希仍然校验下载的包。
- 镜像构建会把基础镜像里的 `zlib1g` 升到当前安全版本。基础镜像快照早于该更新，不升级就会被 Trivy 拦下。
- 扫描的接受风险写在 `.trivyignore.yaml`，每条必须有 `statement` 与 `expired_at`。到期后 Trivy 会重新报出，必须修复或重新评审后延期。当前两条：`filelock` 受 litellm 与 ADK 的版本上限约束无法升级，`setuptools` 只存在于基础镜像被删除的层里，合并后的文件系统没有它。
- 基础镜像的 digest 写在 `Dockerfile` 的 `ARG PYTHON_IMAGE` 里。升级基础镜像是显式提交，重新构建、重新扫描、重新跑门禁。
- 回滚用上一个 digest 重新 apply，不重建镜像。数据库 schema 只做加法，旧镜像可以在新表结构上运行；破坏性变更必须单独评审。
- `gemini` 不在默认镜像里。需要时另建带该 extra 的镜像和锁，不要在生产镜像里临时 `pip install`。

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

## 时钟

- 审批与审计的过期判断用数据库的 `now()`，不是进程时钟。本机实测主机时钟曾比 Postgres 容器快约 4 秒。
- 节点与数据库都必须做 NTP。审批截止时间要远大于时钟偏差；不要把 TTL 设成几秒。
- 审计记录的时间戳由写入进程生成，跨主机排查按 trace id 关联，不依赖时间先后。

## 故障模式

| 故障 | 表现 | 处理 |
| --- | --- | --- |
| Postgres 不可达 | 审批接口 503 `approval_unavailable`；注册表与配额请求失败；审计写入失败 | 恢复数据库，Pod 自动重连；不要切回文件模式 |
| Redis 不可达 | 限流回退到每进程计数 | 容量按单副本上限估算，恢复后自动回到共享计数 |
| `SESSION_URL` 误设为 `memory://` | 会话在副本间不共享 | 改成 Postgres DSN 并滚动 |
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
- 滚动升级前跑一次 `python scripts/check.py --full`，升级后重跑冒烟与验签。
