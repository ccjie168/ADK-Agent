# SLICE-097 审计数据库接线与文件模式回归

状态: merged
依据: ADR-0016 第 2、4 条。

## 意图（要什么，不写怎么写）

SLICE-096 有了 Postgres 审计写读，但命令与服务还没接上。这一刀把审计服务、控制台、注册表服务与三个网关都接到 `--audit-db`/`AUDIT_DATABASE_URL`，并确认文件模式行为不变。

- 所有接受 `--audit-file`/`--audit-url` 的命令增加 `--audit-db`，三选一。
- 未显式给 file/url 时读 `AUDIT_DATABASE_URL`。
- 写用 `PostgresAuditSink`，读用 `PostgresAuditQuery`，签名沿用 `ADK_AUDIT_KEYRING`/`ADK_AUDIT_SIGNING_KEY`。
- `serve-audit` 支持 `--out FILE` 或 `--audit-db URL`，`POST /v1/events` 仍返回记录哈希。
- 文件模式保持现有行为与测试。

## 新增文件

- `tests/audit/test_audit_service_postgres.py`
- `tests/test_cli_audit_db.py`
- `docs/evidence/SLICE-097-audit-db-wiring.txt`
- `docs/specs/SLICE-097-audit-db-wiring.md`

## 修改文件

- `src/adk_agent/audit/postgres.py`（`append` 返回 `AuditRecord`，`emit` 复用它）
- `src/adk_agent/audit/service.py`（可选异步 `query`）
- `src/adk_agent/cli.py`（`--audit-db`、`_audit_sink`/`_audit_query`、`serve-audit`）
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
--audit-file PATH | --audit-url URL | --audit-db URL   三选一
AUDIT_DATABASE_URL 仅在 file 与 url 都未给时生效
同时给两个或 db 与环境变量冲突 -> 退出 2

_audit_sink:
  db -> PostgresAuditSink(url, signing_key, keyring)
_audit_query:
  db -> PostgresAuditQuery(url)

serve-audit --out FILE | --audit-db URL
  DB 模式不接受 --audit-max-records（退出 2）
  DB 模式查询走 query_audit_records

PostgresAuditSink.append(event) -> AuditRecord
PostgresAuditSink.emit(event) -> await append(event)，丢弃返回值
build_audit_pipeline_app(pipeline, *, query: Callable[..., Awaitable[list[AuditEvent]]] | None = None)
```

## 完成判据（可执行）

- [x] 控制台用 `--audit-db` 写入并在审计面板读到 -> `tests/audit/test_audit_service_postgres.py::test_console_db_roundtrip`
- [x] 审计服务 DB 模式 POST 返回哈希且 GET 读到 -> `::test_service_db_roundtrip`
- [x] 审计服务 DB 模式过滤与租户绑定 -> `::test_service_db_tenant_binding`
- [x] 网关的 `_audit_sink` 在 db 模式返回 PostgresAuditSink -> `tests/test_cli_audit_db.py::test_sink_selects_database`
- [x] file/url/db 互斥 -> `::test_audit_backend_exclusive`
- [x] `AUDIT_DATABASE_URL` 回退 -> `::test_audit_db_env_fallback`
- [x] `serve-audit` 必须给 `--out` 或 `--audit-db` -> `::test_serve_audit_requires_a_backend`
- [x] `--audit-max-records` 与 db 互斥 -> `::test_serve_audit_db_rejects_rotation`
- [x] 文件模式回归 -> 现有审计测试全绿
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`console --audit-db URL` -> 当前 argparse 退出 2（参数不存在）
- [x] 反例 2：`serve-audit --audit-db URL`（不给 `--out`）-> 当前退出 2（`--out` 必填）
- [x] 反例 3：`build_audit_pipeline_app(pipeline, query=...)` -> 当前 `TypeError`

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`：新增审计后端选择段，并更新 `serve-audit` 段。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件、后端 URL、签名密钥来源。
2. **调用方**：控制台、注册表服务、三个网关、审计服务、CLI 运维。
3. **信任边界**：每个服务到 Postgres；环境变量里的签名密钥。
4. **恶意输入最坏结果**：多后端同时配置导致写两处或漏写（缓解：显式互斥并退出 2）；网关用不同密钥写同一张表导致验链失败（缓解：契约写明所有写者必须共享同一 keyring，并让 `verify-audit` fail-closed）；DSN 泄露到日志（缓解：错误只报类型，不回显 DSN）；`--audit-max-records` 与 db 混用造成误解（缓解：退出 2）。
5. **失败是否泄露信息**：错误只回固定码；不打印 DSN、密钥或事件内容。

## 范围外

- 审批存储与多副本清单。
- 文件历史导入。
- 审计查询的分页游标。

## 证据

- 反例红：`docs/evidence/SLICE-097-audit-db-wiring.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，控制台与审计服务对同一个 Postgres 库读写，文件模式回归
