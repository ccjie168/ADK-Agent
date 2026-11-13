# ADR-0009 注册表服务与 Postgres 后端

状态: Proposed   日期: 2026-11-13   签字: 待签

## 背景

方向评审（`docs/reviews/architecture-direction-20261113.md`）把控制面列为下一个接缝。现状：注册表是本地目录，控制台和 MCP 直接读文件；多副本部署要么共享卷，要么各自看到不同的目录。ADR-0002 第 8 条要求状态外部化，第 9 条把控制面留在最后拆。工件链（ADR-0008，SLICE-064 到 068）已经让"发布 → 注册 → 按引用运行"跑通，缺的是共享存储和控制面接口。

不决定的后果：市场页只在单机共享卷下成立；发布没有中心审计；多副本无法保证看到同一份注册表。

## 决定

1. **元数据先落 Postgres。** 新增 `PostgresAgentRegistry` 实现现有 `AgentRegistry` 端口，表结构：

   ```sql
   CREATE TABLE adk_agent_versions (
       tenant text NOT NULL,
       agent_id text NOT NULL,
       version text NOT NULL,
       digest text NOT NULL,
       artifact_digest text,
       record jsonb NOT NULL,
       published_at timestamptz NOT NULL,
       PRIMARY KEY (tenant, agent_id, version)
   );
   CREATE INDEX adk_agent_versions_tenant_idx ON adk_agent_versions (tenant, published_at DESC);
   ```

   `record` 是 `PublishedAgent` 的完整 JSON，与文件注册表的记录逐字节同构；`digest`、`artifact_digest` 是冗余列，用于索引与一致性检查。读取时重算 manifest 摘要，不一致抛 `RegistryIntegrityError`。

2. **版本不可变的语义不变。** 发布用 `INSERT ... ON CONFLICT DO NOTHING`；冲突时读出已有记录，`digest` 相同返回已有记录（幂等），不同抛 `RegistryConflict`。tenant、id、version 继续走安全名白名单。

3. **控制面是独立服务。** 新增 `adk-agent serve-registry`，接口：

   - `GET /v1/tenants`：admin 返回全部，其他身份只返回 token 的租户。
   - `GET /v1/agents?tenant=<name>`：该租户的已发布记录列表；缺省取 token 租户，非 admin 跨租户 403。
   - `GET /v1/agents/{tenant}/{id}/{version}`：单条记录，缺失 404。
   - `POST /v1/agents`：请求体是 `PublishedAgent`。服务端校验 manifest 摘要、租户与 token 一致（admin 例外）、工件存在时验签（可信密钥表同 ADR-0008）。成功 201；版本冲突 409；记录非法 400。
   - `PUT /v1/artifacts/{digest}`：请求体是 zip 原始字节，`Content-Type: application/vnd.adk.agent+zip`。服务端校验字节的 sha256 与 `digest` 一致、大小与已发布记录一致、记录签名可信，然后写入 `ArtifactStore`。成功 201；没有对应发布记录 409 `artifact_not_published`；摘要不符 400；超过 8 MiB 413。
   - 鉴权沿用其他服务：只有 `/healthz` 开放，非回环地址没有 token 拒绝启动；OIDC 模式下租户以 token 为准。

4. **发布带工件的顺序。** 先 `POST /v1/agents` 发布元数据并验签，再 `PUT /v1/artifacts/{digest}` 上传字节。两步之间记录可见但不可运行，加载器会报工件缺失。这个窗口是显式的，比接受一份签了名却永远没有字节的记录好。

5. **客户端。** 新增 `HttpAgentRegistry` 实现 `AgentRegistry`。`console`、`serve`、`serve-many` 和 `publish` 接受 `--registry-url URL` 与 `--registry-token-env VAR`（默认 `ADK_REGISTRY_AUTH_TOKEN`）。给 URL 时走 HTTP，否则维持 `--registry DIR` 的文件实现。文件实现降级为单机演示。

6. **不回填文件数据。** 试点环境重新发布即可，记录形状相同、摘要不变。批量导入脚本排在后续切片。

7. **跨副本可见性。** 注册表服务无状态，元数据在 Postgres，工件字节在 `ArtifactStore`（Postgres 或文件）；多个控制台副本指向同一服务即看到同一份目录。控制台不再依赖共享卷。

## 备选与否决

- **控制台自己连 Postgres 读写注册表**：把控制面的信任边界混进 UI 进程，且每个副本都要数据库凭据；否决。
- **继续用文件注册表加共享卷**：违反 ADR-0002 第 8 条，扩容和备份都难；保留为演示实现。
- **发布时一次上传元数据加字节（multipart）**：服务端要同时处理签名与二进制，错误语义和重试都更复杂；拆成两步。
- **先做生命周期状态**：会改 `PublishedAgent` 契约，牵动审计和运行；排在 ADR-0010。

## 后果

- 控制面成为独立接缝，符合 ADR-0002 第 9 条；控制台和 MCP 变成注册表的纯客户端。
- 发布带工件变成两步，脚本和文档要写清顺序。先发布后上传失败时，记录存在但不可运行，重试上传即可。
- 注册表服务需要自己的 token 与可信公钥配置；运维多一个服务。
- 这一版不做 RLS、搜索、生命周期、工件回收。注册表的租户隔离在 API 层强制，数据库角色仍要求最小权限；RLS 等控制面管理员语义确定后再加。
- 后续切片：Postgres 实现与迁移测试、服务与客户端、控制台与 MCP 接线、发布命令接线、市场页改用服务。

## 待签确认

请确认三点，确认后状态改为 Accepted：

1. `adk_agent_versions` 表结构与"版本不可变、digest 相同即幂等"的语义。
2. 控制面五个端点、租户绑定、服务端验签，以及"先发布元数据再上传字节"的两步顺序。
3. 独立进程 `serve-registry`，客户端用 `--registry-url`/`--registry-token-env`，文件注册表只留作演示。
