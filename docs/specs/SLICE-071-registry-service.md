# SLICE-071 注册表控制面服务与客户端

状态: merged
依据: ADR-0009 第 3、4、5 条，`docs/contracts/registry_service.md`，SLICE-070。

## 意图（要什么，不写怎么写）

Postgres 注册表已经能跨副本读写，但还没有共享的 HTTP 接缝。这一刀按契约新增 `serve-registry` 服务与 `HttpAgentRegistry` 客户端，控制台和 MCP 的接线留到 SLICE-072。

- `registry/service.py`：五个端点、租户绑定、服务端摘要与验签、两步发布顺序。
- `registry/client.py`：`HttpAgentRegistry` 实现 `AgentRegistry`，404 映射为 `None`，错误映射按契约。
- `cli.py` 新增 `serve-registry`：`--database-url`（默认 `$REGISTRY_DATABASE_URL`）、`--artifact-dir` 或 `$ARTIFACT_URL`、`--artifact-keys` 或 `$ADK_ARTIFACT_KEYS`，鉴权与限流复用现有中间件。
- 不接线 `console`/`serve`/`serve-many`/`publish` 的 `--registry-url`，那是 SLICE-072。

## 新增文件

- `src/adk_agent/registry/service.py`
- `src/adk_agent/registry/client.py`
- `tests/registry/test_registry_service.py`
- `tests/registry/test_registry_client.py`
- `tests/test_cli_registry_service.py`
- `docs/evidence/SLICE-071-registry-service.txt`

## 修改文件

- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/cli.py`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
build_registry_service_app(registry, *, artifact_store=None, trust=None,
                           host, auth_token, allow_unauthenticated, oidc, rate_limit)

HttpAgentRegistry(base_url, *, auth_token=None, client=None, timeout=10.0)
  get(ref, tenant)    -> PublishedAgent | None
  publish(agent)      -> PublishedAgent | RegistryConflict | RegistryForbidden | RegistryRejected
  list(tenant)        -> list[PublishedAgent]
  tenants()           -> list[str]
  upload_artifact(artifact, data) -> None        # PUT，两步发布的第二步

错误：RegistryServiceUnavailable(RegistryError)
       RegistryForbidden(RegistryError)
       RegistryRejected(RegistryError)
```

## 完成判据（可执行）

- [x] `/healthz` 开放、其余路径要 token -> `tests/registry/test_registry_service.py::test_healthz_open_and_protected`
- [x] 发布后按租户读回 -> `::test_publish_and_get`
- [x] 同版本同内容幂等 -> `::test_publish_is_idempotent`
- [x] 同版本不同内容 409 -> `::test_publish_conflict`
- [x] 摘要与 manifest 不符 400 -> `::test_publish_rejects_bad_digest`
- [x] 带工件但没配置公钥 503 -> `::test_publish_requires_trust_for_artifact`
- [x] 不可信签名 400 -> `::test_publish_rejects_untrusted_artifact`
- [x] 列表与租户 -> `::test_list_and_tenants`
- [x] 版本缺失 404 -> `::test_get_missing`
- [x] OIDC 非 admin 跨租户 403 -> `::test_oidc_cross_tenant_forbidden`
- [x] OIDC 发布他人租户 403 -> `::test_oidc_publish_other_tenant`
- [x] 工件上传写入存储 -> `::test_upload_artifact`
- [x] 没有发布记录 409 -> `::test_upload_without_record`
- [x] 摘要或大小不符 400 -> `::test_upload_mismatch`
- [x] 不可信记录 409 -> `::test_upload_untrusted_record`
- [x] 错误媒体类型 415 -> `::test_upload_wrong_media_type`
- [x] 超限 413 -> `::test_upload_too_large`
- [x] 客户端往返与 404 -> `tests/registry/test_registry_client.py::test_roundtrip_and_missing`
- [x] 客户端错误映射 -> `::test_conflict_and_forbidden_mapping`
- [x] 传输失败映射 -> `::test_transport_failure_maps_to_unavailable`
- [x] `serve-registry` 缺数据库退出 1 -> `tests/test_cli_registry_service.py::test_missing_database_url`
- [x] `serve-registry` 装配服务 -> `::test_builds_service`
- [x] 工件来源二选一 -> `::test_artifact_source_exclusive`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import HttpAgentRegistry` -> 当前 `ImportError`
- [x] 反例 2：`cli.main(["serve-registry", ...])` -> 当前 argparse 退出 2
- [x] 反例 3：带工件但没有可信公钥仍接受发布 -> 当前服务不存在，无此行为

## 契约（如涉及对外接口）

已先改 `docs/contracts/registry_service.md` 与 `docs/contracts/cli.md` 的 `serve-registry` 一节。

## 5 问威胁建模（10 分钟）

1. **数据**：发布记录、manifest、工件摘要、工件字节、token。
2. **调用方**：控制台、MCP、发布脚本、运维。
3. **信任边界**：HTTP 到服务；服务到 Postgres 与工件存储；token 到租户。
4. **恶意输入最坏结果**：跨租户读或写（缓解：OIDC 租户绑定与 403）；伪造摘要（缓解：服务端重算）；上传恶意 zip（缓解：只存字节、不解包；加载器在 SLICE-067 已限制）；超限请求吃内存（缓解：Content-Length 与读后双重 413）；未签名工件进入共享存储（缓解：发布与上传都要求可信公钥）。
5. **失败是否泄露信息**：错误码固定；列表只返回授权租户；不回显 token 与 DSN。

## 范围外

- 控制台、MCP、发布命令的 `--registry-url` 接线（SLICE-072）。
- RLS、搜索、生命周期、工件回收。
- 文件注册表数据回填。

## 证据

- 反例红: `docs/evidence/SLICE-071-registry-service.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真实 Postgres 与两个进程
