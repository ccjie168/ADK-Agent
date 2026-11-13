# 注册表服务契约

`adk-agent serve-registry` 是对已发布 agent 版本的控制面，见 ADR-0009。数据面加载不在这个服务里。

## 鉴权

- 只有 `/healthz` 开放。静态 token 模式要求 `Authorization: Bearer <token>`，OIDC 模式要求合法 JWT。
- 非回环地址没有 token 且没有 OIDC 配置时拒绝启动。
- OIDC 模式下，principal 的 `tenant` 绑定租户，`admin` 角色可以跨租户；静态 token 模式视为单一运维操作者，不限制租户。
- 无权访问其他租户返回 403 `{"error":"tenant_forbidden"}`。

## `GET /v1/tenants`

返回 200 `{"tenants": ["<name>", ...]}`，按名字排序。OIDC 非 admin 只返回自己的租户。

## `GET /v1/agents?tenant=<name>`

返回 200 `{"agents": [PublishedAgent, ...], "count": <n>}`。省略 `tenant` 时取 token 租户；静态 token 模式省略时返回全部租户，按 `(tenant, agent_id, version)` 排序。OIDC 非 admin 跨租户 403。

`PublishedAgent` 形状见 `manifest.schema.json` 加 `digest`、`signature`、`published_at`、可选 `artifact`；它不是独立 schema 文件。

## `GET /v1/agents/{tenant}/{id}/{version}`

返回 200，正文是一条 `PublishedAgent`。不存在返回 404 `{"error":"not_found"}`。OIDC 非 admin 跨租户 403。

## `POST /v1/agents`

请求体是一条 `PublishedAgent`。

- 校验：模型合法，`manifest_digest(manifest) == digest`，OIDC 模式下 manifest 的租户等于 token 租户（admin 例外）。
- 记录带 `artifact` 时要求服务配置了可信公钥，且签名可验证；没配置返回 503 `artifact_trust_unavailable`，验证失败返回 400 `artifact_untrusted`。
- 成功返回 201，正文是已存记录。同一版本同 digest 重发返回 201 和已有记录，幂等。
- 同一版本不同 digest 返回 409 `{"error":"version_conflict"}`。
- 请求体不是 JSON 返回 400 `invalid_json`；模型或摘要不符返回 400 `invalid_record`。

## `PUT /v1/artifacts/{digest}`

请求体是工件 zip 原始字节，`Content-Type` 必须是 `application/vnd.adk.agent+zip`，否则 415 `unsupported_media_type`。`digest` 必须匹配 `sha256:[0-9a-f]{64}`，否则 400 `invalid_digest`。

- 服务端先检查大小，超过 8 MiB 返回 413 `{"error":"too_large"}`。
- 再找引用该摘要的已发布记录（OIDC 模式只在 token 租户内找），找不到返回 409 `{"error":"artifact_not_published"}`。
- 字节的 sha256 与 `digest` 不符返回 400 `digest_mismatch`；大小与记录不符返回 400 `size_mismatch`。
- 记录签名必须可信，否则 409 `artifact_untrusted`。
- 成功写入 `ArtifactStore` 返回 201 `{"digest": "sha256:<hex>", "size": <n>}`。重复上传同一摘要返回 201，幂等。

## `GET /v1/agents/{tenant}/{agent_id}/{version}/eval`

返回 200，正文是一条 `EvalReport`（结构见 `eval_report.schema.json`）。OIDC 非 admin 跨租户 403。没有报告返回 404 `{"error":"eval_report_not_found"}`。评测报告存储不可用返回 502 `eval_store_unavailable`。

## `PUT /v1/agents/{tenant}/{agent_id}/{version}/eval`

请求体是一条 `EvalReport`。版本必须已发布，否则 404 `{"error":"not_found"}`；OIDC 非 admin 跨租户 403。

- 请求体不是 JSON 返回 400 `invalid_json`，模型非法返回 400 `invalid_report`。
- 成功返回 201 和已存报告。同一版本同内容重复提交返回 201，幂等。
- 同一版本不同内容返回 409 `{"error":"eval_report_conflict"}`。
- 存储不可达返回 502 `{"error":"eval_store_unavailable"}`。

评测报告与发布记录同库存储在 `adk_eval_reports`，服务总是配置这个存储。

## `GET /v1/agents/{tenant}/{agent_id}/{version}/lifecycle`

返回 200：

```json
{"status": "published", "changed_at": null, "changed_by": null, "reason": ""}
```

没有生命周期行时就是上面这份默认值。OIDC 非 admin 跨租户 403。生命周期存储不可用返回 503 `lifecycle_store_unavailable`。

`GET /v1/agents` 与单条读取的每个版本额外带只读字段 `lifecycle`，形状与上面相同。它是服务层附加字段，不属于 `PublishedAgent`。

## `PUT /v1/agents/{tenant}/{agent_id}/{version}/lifecycle`

请求体：

```json
{"status": "deprecated", "reason": "superseded by 1.1.0"}
```

- `status` 取 `published`、`deprecated`、`retired`。非法值 400 `invalid_status`；请求体不是 JSON 或不是对象 400 `invalid_request`。
- 版本必须已发布，否则 404 `not_found`。
- 只有 admin 或静态 token 操作者可以改。OIDC 非 admin 返回 403 `forbidden`；跨租户仍按 403 `tenant_forbidden`。
- 非法转换（`retired` 到其他状态）返回 409 `invalid_transition`。设置成当前状态是幂等的，返回 200 且不更新 `changed_at`。
- 成功返回 200 和新的生命周期记录。变化写一条 `agent.lifecycle` 审计，`target` 是 `<tenant>/<id>@<version>`，状态为 `ok`。
- 生命周期存储不可用返回 503 `lifecycle_store_unavailable`。

## 错误

| 状态 | 错误码 | 含义 |
| --- | --- | --- |
| 400 | `invalid_json` | 请求体不是 JSON |
| 400 | `invalid_record` | `PublishedAgent` 非法或摘要与 manifest 不符 |
| 400 | `invalid_digest` | 路径里的摘要格式不对 |
| 400 | `digest_mismatch` | 上传字节与摘要不符 |
| 400 | `size_mismatch` | 上传字节大小与记录不符 |
| 400 | `artifact_untrusted` | 工件签名不可信 |
| 400 | `invalid_report` | `EvalReport` 非法 |
| 400 | `invalid_status` | 生命周期状态非法 |
| 400 | `invalid_request` | 生命周期请求体非法 |
| 401 | `unauthorized` | 缺少或错误的凭证 |
| 403 | `tenant_forbidden` | 跨租户访问 |
| 403 | `forbidden` | 非 admin 修改生命周期 |
| 404 | `not_found` | 版本不存在 |
| 404 | `eval_report_not_found` | 该版本没有评测报告 |
| 409 | `version_conflict` | 同版本不同内容 |
| 409 | `artifact_not_published` | 没有引用该摘要的发布记录 |
| 409 | `artifact_untrusted` | 上传时记录的签名不可信 |
| 409 | `eval_report_conflict` | 同版本已有不同评测报告 |
| 409 | `invalid_transition` | 生命周期转换非法 |
| 413 | `too_large` | 超过 8 MiB |
| 415 | `unsupported_media_type` | 工件 Content-Type 不对 |
| 502 | `artifact_store_failed` | 工件存储写入失败 |
| 502 | `eval_store_unavailable` | 评测报告存储不可用 |
| 502 | `registry_unavailable` | 注册表存储不可达 |
| 502 | `registry_integrity_error` | 存储的记录与摘要不符 |
| 503 | `artifact_store_unavailable` | 服务没有配置工件存储 |
| 503 | `lifecycle_store_unavailable` | 服务没有配置生命周期存储 |
| 503 | `artifact_trust_unavailable` | 发布带工件但服务没有可信公钥 |

## 客户端

`HttpAgentRegistry` 实现 `AgentRegistry` 端口，`--registry-url` 指向本服务，`--registry-token-env`（默认 `ADK_REGISTRY_AUTH_TOKEN`）指定 token 所在环境变量。

- `publish` 返回非 2xx 时，409 映射为 `RegistryConflict`，401 和 403 映射为 `RegistryForbidden`，400 映射为 `RegistryRejected`，传输失败和 5xx 映射为 `RegistryServiceUnavailable`。
- `get` 的 404 映射为 `None`，与文件实现一致。
- token 缺失时客户端仍可连回环地址上的未鉴权服务；非回环服务缺 token 时，第一次调用报 `RegistryServiceUnavailable` 并带 401。

## 发布顺序

带工件的发布是两步：先 `POST /v1/agents`，再 `PUT /v1/artifacts/{digest}`。第一步成功后第二步失败时，记录可见但不可运行，重试上传即可。客户端命令 `publish --registry-url` 按这个顺序发。
