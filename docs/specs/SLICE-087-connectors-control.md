# SLICE-087 连接器控制面、控制台与命令

状态: merged
依据: ADR-0013 第 1、5 条。

## 意图（要什么，不写怎么写）

连接器已有类型、存储与执行，但还没有人能用。这一刀补齐控制面接口、HTTP 客户端、控制台面板和 CLI。

- `serve-registry` 复用主数据库，暴露连接器的读、注册与停用接口；只有 admin 或静态 token 操作者能写。
- `HttpConnectorStore` 实现 `ConnectorStore` 端口，把 409/404/403 映射成现有连接器错误。
- 控制台增加 Connectors 面板与三个接口；本地用 `--connectors-dir`，远端复用 `--registry-url`。
- CLI `adk-agent connectors list|register|disable`，本地文件或控制面。
- 注册与停用写 `connector.register` / `connector.disable` 审计。
- 工具目录暂时仍是静态文件；连接器工具进目录留给后续。

## 新增文件

- `src/adk_agent/registry/connectors_client.py`
- `tests/registry/test_connector_service.py`
- `tests/registry/test_connector_client.py`
- `tests/test_console_connectors.py`
- `tests/test_cli_connectors.py`
- `docs/evidence/SLICE-087-connectors-control.txt`

## 修改文件

- `src/adk_agent/core/connectors.py`（`ConnectorForbidden`）
- `src/adk_agent/registry/__init__.py`、`registry/service.py`
- `src/adk_agent/console.py`
- `src/adk_agent/cli.py`
- `docs/contracts/registry_service.md`、`console.md`、`cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GET  /v1/connectors?tenant=T      -> {"connectors": [ConnectorSpec], "count": n}
GET  /v1/connectors/{id}          -> ConnectorSpec
POST /v1/connectors               -> 201 ConnectorSpec
POST /v1/connectors/{id}/disable  -> 200 ConnectorSpec

console:
GET  /api/connectors?tenant=T
POST /api/connectors
POST /api/connectors/{id}/disable

CLI:
connectors list --tenant T [--connectors-dir DIR | --registry-url URL]
connectors register --id ... [--connectors-dir DIR | --registry-url URL]
connectors disable --id ID [--connectors-dir DIR | --registry-url URL]
```

## 完成判据（可执行）

- [x] 列表返回全局与租户连接器 -> `tests/registry/test_connector_service.py::test_list_visibility`
- [x] 注册成功并写审计 -> `::test_register_and_audit`
- [x] 同 id 不同定义冲突 -> `::test_register_conflict`
- [x] 非 admin 写入被拒 -> `::test_non_admin_forbidden`
- [x] 停用幂等 -> `::test_disable_idempotent`
- [x] 读单条与未知 id -> `::test_get_connector`
- [x] 未配置存储返回 503 -> `::test_store_not_configured`
- [x] HTTP 客户端映射错误 -> `tests/registry/test_connector_client.py`
- [x] 控制台注册、列表与停用 -> `tests/test_console_connectors.py`
- [x] CLI 本地文件 list/register/disable -> `tests/test_cli_connectors.py`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import HttpConnectorStore` -> 当前 `ImportError`
- [x] 反例 2：`GET /v1/connectors` -> 当前 404
- [x] 反例 3：`adk-agent connectors list` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/registry_service.md`、`console.md`、`cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：连接器端点、凭据引用、方法/路径白名单、租户。
2. **调用方**：admin 控制台、CLI、工具网关。
3. **信任边界**：控制面请求到连接器存储；控制台表单到出站配置。
4. **恶意输入最坏结果**：非 admin 注册任意出站端点（缓解：写接口只允许 admin 或静态操作者）；跨租户读取或停用（缓解：租户可见性检查）；明文凭据入库（缓解：`ConnectorSpec` 只接受 `secret://`）；审计缺失（缓解：注册与停用同步写审计）。
5. **失败是否泄露信息**：错误只回固定错误码，不回显 DSN、令牌或存储细节。

## 范围外

- 连接器健康检查。
- 把连接器自动并入工具目录。
- OAuth 与令牌刷新。

## 证据

- 反例红: `docs/evidence/SLICE-087-connectors-control.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres 控制面貌与回环控制台
