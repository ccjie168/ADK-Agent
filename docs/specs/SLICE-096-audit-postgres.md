# SLICE-096 审计的 Postgres 写、读与验链

状态: merged
依据: ADR-0016 第 1、2 条。

## 意图（要什么，不写怎么写）

审计仍写在 JSONL，多副本无法共享。这一刀落 Postgres 的写、读与验链，按租户各一条哈希链，与现有文件实现语义一致。服务与网关的接线留给 097。

- 新增 `PostgresAuditSink`：事务内按租户取 advisory lock，读该租户最后一条，算哈希与签名后插入。
- 新增 `query_audit_records` 与 `PostgresAuditQuery`，过滤条件与限额同 `query_events`。
- 新增数据库验链，`verify-audit` 增加 `--audit-db`，与文件模式二选一。
- 复用现有 `record_hash`、`record_signature` 与密钥环选择逻辑，不改链算法。

## 新增文件

- `src/adk_agent/audit/postgres.py`
- `tests/audit/test_audit_postgres.py`
- `docs/evidence/SLICE-096-audit-postgres.txt`
- `docs/specs/SLICE-096-audit-postgres.md`

## 修改文件

- `src/adk_agent/audit/__init__.py`
- `src/adk_agent/cli.py`（`verify-audit --audit-db`）
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
adk_audit_records (
  tenant text not null,
  sequence bigint not null,
  event jsonb not null,
  prev_hash text not null,
  hash text not null,
  signature text,
  kid text,
  action text not null,
  status text not null,
  trace_id text not null,
  run_id text not null,
  occurred_at timestamptz not null,
  primary key (tenant, sequence)
)
索引: (tenant, occurred_at desc), (trace_id), (run_id), (action), (status)

PostgresAuditSink(url, *, signing_key=None, keyring=None)
  emit(event):
    BEGIN
      SELECT pg_advisory_xact_lock(hashtext('adk_audit:' || tenant))
      SELECT sequence, hash FROM adk_audit_records
        WHERE tenant = $1 ORDER BY sequence DESC LIMIT 1
      prev = 上一条 hash 或 ""
      seq = 上一条 sequence + 1 或 1
      hash = record_hash(event, prev)
      signature/kid 按 signing_key 或 keyring.active
      INSERT
    COMMIT

query_audit_records(url, *, tenant, trace_id, run_id, action, status,
                    since, until, limit=100, order="desc") -> list[AuditEvent]
verify_audit_database(url, *, signing_key=None, keyring=None) -> int
CLI: verify-audit (FILE | --audit-db URL)，二选一
```

## 完成判据（可执行）

- [x] 两个租户各自从 1 开始编号且链可验 -> `tests/audit/test_audit_postgres.py::test_per_tenant_chains`
- [x] 同租户并发写序列唯一且链完整 -> `::test_concurrent_writes`
- [x] 查询过滤与排序与文件实现一致 -> `::test_query_filters`
- [x] 篡改事件后验链失败 -> `::test_tamper_detected`
- [x] 签名模式能验签，缺签名失败 -> `::test_signatures`
- [x] CLI `verify-audit --audit-db` 通过 -> `::test_cli_verify_database`
- [x] FILE 与 `--audit-db` 互斥 -> `tests/test_registry_cli.py` 或同文件 `::test_cli_verify_exclusive`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.audit import PostgresAuditSink` -> 当前 `ImportError`
- [x] 反例 2：`adk-agent verify-audit --audit-db URL` -> 当前 argparse 退出 2
- [x] 反例 3：`SELECT to_regclass('adk_audit_records')` -> 当前为 `null`

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md` 的 `verify-audit` 段。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件、租户内序号、前后哈希、签名与 kid。
2. **调用方**：控制台、网关、审计服务、运维。
3. **信任边界**：进程到 Postgres；验链读取到密钥环。
4. **恶意输入最坏结果**：并发写坏链（缓解：租户级 advisory lock 串行化）；跨租户编号混用（缓解：主键与查询都带 tenant）；篡改后仍通过（缓解：重算哈希并验签）；读路径跨租户泄露（缓解：服务层租户过滤，这一刀只提供带 tenant 的查询）；锁等待无上限（缓解：沿用数据库默认与连接池超时，异常原样抛出）。
5. **失败是否泄露信息**：错误只说明断链的记录序号与租户；不回显事件内容或 DSN。

## 范围外

- 服务、控制台与网关切换到 `--audit-db`（097）。
- 文件历史导入 Postgres。
- RLS。
- 审批的 Postgres 存储。

## 证据

- 反例红：`docs/evidence/SLICE-096-audit-postgres.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，真实 Postgres 上两租户并发写、验链与篡改检测
