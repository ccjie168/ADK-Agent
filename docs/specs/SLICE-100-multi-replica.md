# SLICE-100 多副本部署清单与运维手册

状态: merged
依据: ADR-0016 第 4 条、ADR-0017 第 5 条，以及 098/099 完成后的共享存储清单。

## 意图（要什么，不写怎么写）

共享状态已经全部落到 Postgres 与 Redis，单副本清单还带着 SQLite 和 PVC。这一刀给出可复制的多副本示例与运维手册，作为 Phase E 的收口。它不是生产发行版，不引入 Helm、Operator 或新的运行时依赖。

- `deploy/k8s/multi-replica.yaml` 声明四个无本地卷的 Deployment：控制台、MCP 网关、审计服务、注册表服务，每项至少两个副本。
- 所有共享状态用环境变量指向 Postgres / Redis，DSN 与密钥只从 Secret 引用；清单里没有任何明文密钥、PVC、StatefulSet 或 `SESSION_DB`。
- 每个容器有 `/healthz` 就绪与存活探针；Service 用 ClusterIP，示例不暴露公网入口。
- `docs/guides/operations.md` 记录：拓扑与环境变量矩阵、首次部署顺序、扩缩容规则、备份恢复、审计密钥轮换、时钟同步、故障模式、值守检查。
- `tests/test_deploy_manifests.py` 用纯文本结构断言守住清单契约，不引入 YAML 解析依赖。

## 新增文件

- `deploy/k8s/multi-replica.yaml`
- `docs/guides/operations.md`
- `tests/test_deploy_manifests.py`
- `docs/evidence/SLICE-100-multi-replica.txt`
- `docs/specs/SLICE-100-multi-replica.md`

## 修改文件

- `deploy/k8s/secret.example.yaml`（补齐共享 DSN 与密钥环的占位键）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 部署形状

```text
Deployment adk-console   replicas 3  -> Service adk-console:80   (ClusterIP)
Deployment adk-mcp       replicas 3  -> Service adk-mcp:80       (ClusterIP)
Deployment adk-audit     replicas 2  -> Service adk-audit:80     (ClusterIP)
Deployment adk-registry  replicas 2  -> Service adk-registry:80  (ClusterIP)
PodDisruptionBudget adk-console           minAvailable 2

共享状态（全部来自 Secret seed）:
  SESSION_URL            ADK 会话
  REGISTRY_DATABASE_URL  发布版本、生命周期、评测报告、连接器、工具授权
  ARTIFACT_URL           工件字节
  AUDIT_DATABASE_URL     审计链
  APPROVAL_DATABASE_URL  审批
  GRANT_URL              工具授权存储
  QUOTA_URL              配额
  RATE_LIMIT_URL         Redis 限流
  ADK_AUDIT_KEYRING      签名密钥环
  ADK_MCP_AUTH_TOKEN     示例 Bearer token

禁止: PVC、StatefulSet、SESSION_DB、明文密钥、per-pod 本地状态。
```

## 完成判据（可执行）

- [x] 清单结构 -> `tests/test_deploy_manifests.py::test_multi_replica_manifest_shapes`
- [x] 无本地状态 -> `::test_multi_replica_manifest_has_no_local_state`
- [x] 共享后端与 Secret 引用 -> `::test_multi_replica_manifest_uses_shared_backends`
- [x] 手册章节齐全 -> `::test_operations_runbook_sections`
- [x] 单副本旧清单作为反例仍可识别 -> `::test_single_replica_manifest_is_not_mistaken_for_multi`
- [x] `python scripts/check.py --full` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`pytest tests/test_deploy_manifests.py` -> 当前文件不存在，收集失败
- [x] 反例 2：把同样的结构断言指向旧清单 `deploy/k8s/deployment.yaml` -> `replicas: 1`、存在 PVC、存在 `SESSION_DB`，断言失败

## 契约（如涉及对外接口）

不涉及运行时接口。清单里的环境变量名以 `cli.md` 与既有 ADR 为准，不新增变量。

## 5 问威胁建模（10 分钟）

1. **数据**：会话、发布版本、工件、审计链、审批、授权、配额、限流计数。
2. **调用方**：集群内控制台、MCP 客户端、A2A peer、运维 kubectl。
3. **信任边界**：Pod 到共享 Postgres/Redis；Secret 到 Pod；集群网络到 Service。
4. **恶意输入最坏结果**：清单含明文密钥（缓解：只用 `secretKeyRef` 示例键名）；副本间状态分裂（缓解：禁止 PVC 与 `SESSION_DB`）；审计链被一个密钥环锁死（缓解：手册要求所有写方共享同一 Secret，轮换用 `legacy`）；公网暴露（缓解：示例只用 ClusterIP，手册要求入口层 TLS）。
5. **失败是否泄露信息**：探针只回 200/非 200；手册要求错误与指标不包含 DSN 或 token。

## 范围外

- Helm chart、Operator、HPA、服务网格、TLS 终止。
- 托管 Postgres/Redis 的供给与调参。
- RLS 与网络策略的具体实现。
- 镜像构建与签名（已有 Dockerfile，不在本切片）。

## 证据

- 反例红：`docs/evidence/SLICE-100-multi-replica.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
