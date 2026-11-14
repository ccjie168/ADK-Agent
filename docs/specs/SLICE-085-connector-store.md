# SLICE-085 连接器类型与存储

状态: merged
依据: ADR-0013 第 1、2 条。

## 意图（要什么，不写怎么写）

先把连接器的领域类型与存储做出来。出站执行、控制台与命令留给 086 和 087。

- `core/connectors.py`：`ConnectorSpec`、`ConnectorKind`、`HttpMethod` 与存储错误类型；校验 scheme、回环 http、`secret://` 引用、方法/路径/超时/响应大小。
- `ConnectorStore` 端口：注册、读取、按租户列出（全局 + 本租户）、停用。
- 文件实现供单机开发；Postgres 表 `adk_connectors` 供多副本。
- 注册同 id 同内容幂等，不同内容冲突；停用是幂等的状态变更，不删除记录。

## 新增文件

- `src/adk_agent/core/connectors.py`
- `src/adk_agent/registry/connectors.py`
- `src/adk_agent/registry/connectors_postgres.py`
- `tests/core/test_connectors.py`
- `tests/registry/test_connector_store.py`
- `docs/evidence/SLICE-085-connector-store.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`、`core/ports.py`
- `src/adk_agent/registry/__init__.py`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ConnectorKind = http | openapi | mcp
HttpMethod = GET | POST | PUT | PATCH | DELETE | HEAD

ConnectorSpec {
  connector_id, tenant?, kind, base_url, auth_ref?, methods,
  path_prefixes, data_classes, timeout_seconds, max_response_bytes, enabled
}

ConnectorStore:
  add(spec) -> spec
  get(id) -> spec | null
  list(tenant) -> [spec]
  disable(id, by) -> spec
```

## 完成判据（可执行）

- [x] 合法 spec -> `tests/core/test_connectors.py::test_valid_spec`
- [x] 非回环 http 被拒 -> `::test_http_only_loopback`
- [x] 非法 secret 引用被拒 -> `::test_secret_reference`
- [x] 超时与响应大小边界 -> `::test_limits`
- [x] 文件注册幂等与冲突 -> `tests/registry/test_connector_store.py::test_file_add_idempotent`
- [x] 全局与租户可见性 -> `::test_file_list_visibility`
- [x] 停用幂等 -> `::test_file_disable`
- [x] Postgres 同套语义 -> `::test_postgres_lifecycle`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import ConnectorSpec` -> 当前 `ImportError`
- [x] 反例 2：非回环 http 被接受 -> 当前无此校验

## 契约（如涉及对外接口）

不涉及；控制台接口在 SLICE-087 先改契约。

## 5 问威胁建模（10 分钟）

1. **数据**：端点、方法、路径前缀、凭据引用、数据分级、超时。
2. **调用方**：控制面、执行适配器、工具目录。
3. **信任边界**：注册记录到出站请求；SecretProvider 到凭据。
4. **恶意输入最坏结果**：明文凭据入库（缓解：只接受 `secret://`）；内网 http 探测（缓解：https 或回环）；路径逃逸（缓解：前缀必须以 `/` 开头且拒绝 `..`）；超大响应（缓解：上限 8 MiB）。
5. **失败是否泄露信息**：错误只报字段与枚举。

## 范围外

- 出站执行与审计（SLICE-086）。
- 控制台与 CLI（SLICE-087）。
- OAuth、令牌刷新、响应转换。

## 证据

- 反例红: `docs/evidence/SLICE-085-connector-store.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres
