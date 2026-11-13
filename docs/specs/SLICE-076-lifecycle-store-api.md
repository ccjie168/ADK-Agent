# SLICE-076 生命周期存储与控制面接口

状态: merged
依据: ADR-0010 第 1、2、3 条，`docs/contracts/registry_service.md`。

## 意图（要什么，不写怎么写）

ADR-0010 签字后，先把状态存起来并提供控制面读写。加载拦截、控制台徽标和 CLI 命令留给 SLICE-077。

- 核心模型 `AgentLifecycle` 与转换函数：`published`/`deprecated`/`retired`，退役终态，重复设置幂等。
- `AgentLifecycleStore` 端口，文件与 Postgres 两个实现。缺行视为 `published`。
- 注册表服务 `GET/PUT /v1/agents/{tenant}/{id}/{version}/lifecycle`；列表与单条读取附带只读 `lifecycle`。
- 只有 admin 或静态 token 操作者可改；变化写 `agent.lifecycle` 审计。
- `serve-registry` 自动配置 Postgres 生命周期存储，并接受现有审计参数。
- `HttpAgentRegistry` 增补 `get_lifecycle`/`set_lifecycle`。

## 新增文件

- `src/adk_agent/core/lifecycle.py`
- `src/adk_agent/registry/lifecycle.py`（文件实现）
- `src/adk_agent/registry/lifecycle_postgres.py`
- `tests/core/test_lifecycle.py`
- `tests/registry/test_lifecycle_store.py`
- `tests/registry/test_registry_lifecycle_service.py`
- `docs/evidence/SLICE-076-lifecycle-store-api.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`、`core/ports.py`
- `src/adk_agent/registry/__init__.py`、`service.py`、`client.py`
- `src/adk_agent/cli.py`
- `scripts/export_contracts.py`、`docs/contracts/agent_lifecycle.schema.json`、`docs/contracts/README.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
LifecycleStatus = "published" | "deprecated" | "retired"
AgentLifecycle {status, changed_at: datetime | null, changed_by: str | null, reason: str}

adk_agent_lifecycle(tenant, agent_id, version, status, changed_at, changed_by, reason)

允许：published -> deprecated | retired
      deprecated -> published | retired
      retired    -> retired（幂等）；其他 -> LifecycleTransitionError
```

## 完成判据（可执行）

- [x] 转换矩阵 -> `tests/core/test_lifecycle.py::test_transition_matrix`
- [x] 退役终态 -> `::test_retired_is_terminal`
- [x] 重复设置幂等 -> `::test_idempotent_set`
- [x] 文件存储往返与默认值 -> `tests/registry/test_lifecycle_store.py::test_file_roundtrip`
- [x] 文件存储非法转换 -> `::test_file_rejects_transition`
- [x] Postgres 存储往返与并发幂等 -> `::test_postgres_roundtrip`
- [x] 服务默认 published -> `tests/registry/test_registry_lifecycle_service.py::test_default_published`
- [x] 服务设置与读取 -> `::test_set_and_get`
- [x] 非 admin 403 -> `::test_non_admin_forbidden`
- [x] 版本不存在 404 -> `::test_version_required`
- [x] 非法转换 409 -> `::test_invalid_transition`
- [x] 非法状态 400 -> `::test_invalid_status`
- [x] 变化写审计 -> `::test_audit_records_change`
- [x] 客户端往返 -> `::test_client_roundtrip`
- [x] `serve-registry` 装配存储 -> `tests/test_cli_registry_service.py::test_builds_lifecycle_store`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import AgentLifecycle` -> 当前 `ImportError`
- [x] 反例 2：`GET .../lifecycle` -> 当前 404
- [x] 反例 3：`serve-registry` 没有生命周期存储参数 -> 服务不接受该配置

## 契约（如涉及对外接口）

已先改 `docs/contracts/registry_service.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：状态、操作者、原因、变更时间。
2. **调用方**：运维、控制台、发布脚本。
3. **信任边界**：HTTP 到服务；服务到共享存储；角色到写权限。
4. **恶意输入最坏结果**：非 admin 下线别人版本（缓解：admin 写权限与 403）；复活已退役版本（缓解：终态转换拒绝）；并发重复下线覆盖变更者（缓解：行锁与幂等语义）；原因字段注入（缓解：纯文本审计，不渲染 HTML）。
5. **失败是否泄露信息**：错误码固定；不返回 DSN。

## 范围外

- 加载与启动拦截（SLICE-077）。
- 控制台徽标与 CLI 命令（SLICE-077）。
- 自动回滚、保留策略、删除。
- 历史变更列表（审计里有，控制面暂不提供）。

## 证据

- 反例红: `docs/evidence/SLICE-076-lifecycle-store-api.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres
