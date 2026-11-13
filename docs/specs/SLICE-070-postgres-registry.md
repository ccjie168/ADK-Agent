# SLICE-070 Postgres 注册表

状态: merged
依据: ADR-0009 第 1、2、6 条，SLICE-012，SLICE-065。

## 意图（要什么，不写怎么写）

文件注册表只在一个共享卷上成立。这一刀按 ADR-0009 新增 `PostgresAgentRegistry`，实现现有 `AgentRegistry` 端口，把已发布版本放进 `adk_agent_versions`。控制面服务与客户端留到 SLICE-071。

- 表结构按 ADR-0009 第 1 条；`record` 是 `PublishedAgent` 的完整 JSON，`digest` 与 `artifact_digest` 是冗余列。
- 发布是 `INSERT ... ON CONFLICT DO NOTHING`；随后读出既有行，digest 相同返回既有记录，不同抛 `RegistryConflict`。
- 读取时重算 manifest 摘要，不一致抛 `RegistryIntegrityError`；`get` 的租户、id、version 或 digest 不匹配返回 `None`，与文件实现一致。
- 数据库不可达或驱动缺失抛 `RegistryStoreUnavailable`，它是 `RegistryError` 的子类。
- 不新增 CLI 参数，不接线控制台，不回填文件数据。

## 新增文件

- `src/adk_agent/registry/postgres.py`
- `src/adk_agent/pg.py`（共享惰性连接池）
- `tests/registry/test_registry_postgres.py`
- `docs/evidence/SLICE-070-postgres-registry.txt`

## 修改文件

- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/registry/artifacts_postgres.py`、`src/adk_agent/runtime/quota_postgres.py`（改用共享连接池）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
adk_agent_versions(
  tenant text, agent_id text, version text,
  digest text, artifact_digest text | null,
  record jsonb, published_at timestamptz,
  PRIMARY KEY (tenant, agent_id, version)
)
index: (tenant, published_at DESC)

PostgresAgentRegistry(url)
  publish(PublishedAgent) -> PublishedAgent | RegistryConflict
  get(AgentRef, tenant)   -> PublishedAgent | None | RegistryIntegrityError
  list(tenant)            -> list[PublishedAgent]
  tenants()               -> list[str]
```

## 完成判据（可执行）

- [x] 非 Postgres URL 立即被拒 -> `tests/registry/test_registry_postgres.py::test_unsupported_url_rejected`
- [x] 发布后按引用读回 -> `::test_live_publish_then_get`
- [x] 重复发布返回既有记录 -> `::test_live_publish_is_idempotent`
- [x] 同版本不同内容冲突 -> `::test_live_conflict_on_different_digest`
- [x] 列表与租户按序返回 -> `::test_live_list_and_tenants`
- [x] digest 不匹配返回 None -> `::test_live_get_miss_returns_none`
- [x] 被篡改的记录报完整性问题 -> `::test_live_tampered_record_raises`
- [x] 不可达数据库报 `RegistryStoreUnavailable` -> `::test_live_unreachable_database`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import PostgresAgentRegistry` -> 当前 `ImportError`
- [x] 反例 2：非 Postgres URL 被接受 -> 当前类不存在，无此行为
- [x] 反例 3：同一版本换内容仍能发布 -> 当前无 Store，无法验证；实现后由冲突用例守住

## 契约（如涉及对外接口）

不涉及。`AgentRegistry` 端口不变，控制面接口在 SLICE-071 先改 `docs/contracts/`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、agent id、version、摘要、`PublishedAgent` JSON、工件摘要。
2. **调用方**：控制台、MCP、发布脚本，之后是注册表服务。
3. **信任边界**：进程到共享数据库；数据库里可能被直接改写的记录。
4. **恶意输入最坏结果**：改写 `record` 让摘要与内容不符（缓解：读取时重算摘要）；同版本覆盖已发布内容（缓解：主键加冲突判定）；SQL 注入（缓解：全部参数化）；表名注入（不拼接标识符）。
5. **失败是否泄露信息**：错误只报阶段与异常类型，不回显 DSN 与记录内容。

## 范围外

- `serve-registry` 控制面与 `HttpAgentRegistry`（SLICE-071）。
- CLI 接线与市场页切换。
- RLS、搜索、生命周期、工件回收。
- 文件数据回填。

## 证据

- 反例红: `docs/evidence/SLICE-070-postgres-registry.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真实 Postgres 15 容器
