# SLICE-035 审计管线独立部署（M5-4）

状态: gated
依据: ADR-0002 第 6、9 条，ADR-0006

## 意图（要什么，不写怎么写）

拆出最后一个接缝，并补上租户哈希链。

- `AuditRecord` 是存储记录：event + prev_hash + hash。
- 每租户一条链，启动时从文件重建最后哈希。
- 审计服务接收事件、落盘、fsync 后返回 202 和哈希。
- 服务不可用时调用方拿到 `AuditSinkUnavailable`，不吞错。
- `HttpAuditSink` 实现 `AuditSink` 端口。
- `verify-audit` 命令逐条重算，断链退出 1。
- 服务鉴权沿用 ADR-0004：只有 `/healthz` 开放。
- 这一刀不做日期分区、轮转、集中存储和重试。

## 新增文件

- `src/adk_agent/audit/pipeline.py`
- `src/adk_agent/audit/service.py`
- `src/adk_agent/audit/http_sink.py`
- `tests/audit/test_pipeline.py`
- `tests/audit/test_http_sink.py`
- `docs/contracts/audit_record.schema.json`
- `docs/evidence/SLICE-035-audit-pipeline.txt`
- `docs/evidence/M5-milestone.txt`

## 修改文件

- `src/adk_agent/core/audit.py`：`AuditRecord`
- `src/adk_agent/core/__init__.py`：导出
- `src/adk_agent/audit/__init__.py`：导出
- `src/adk_agent/cli.py`：`serve-audit`、`verify-audit`
- `scripts/export_contracts.py`：导出新 schema
- `docs/contracts/cli.md`：新命令
- `docs/specs/ROADMAP.md`：M5 收口

## 完成判据（可执行）

- [x] 记录契约往返 -> `tests/audit/test_pipeline.py::test_record_contract_roundtrip`
- [x] 同租户形成链 -> `::test_same_tenant_links_records`
- [x] 跨租户独立链 -> `::test_tenants_have_separate_chains`
- [x] 重建后继续追加 -> `::test_restart_resumes_chain`
- [x] 校验通过 -> `::test_verify_accepts_valid_file`
- [x] 篡改被检出 -> `::test_verify_detects_tampering`
- [x] 审计服务鉴权 -> `tests/audit/test_http_sink.py::test_healthz_open_and_events_protected`
- [x] 客户端投递并落盘 -> `::test_client_roundtrip`
- [x] 客户端错误 token 抛错 -> `::test_client_rejects_bad_token`
- [x] 网络绑定需要 token -> `::test_network_bind_requires_token`
- [x] `verify-audit` 成功与失败 -> `tests/audit/test_pipeline.py::test_verify_command`
- [x] 契约 schema 同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.audit.pipeline import AuditPipeline` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.audit.http_sink import HttpAuditSink` -> 当前 `ImportError`
- [x] 反例 3：篡改中间记录后校验仍通过 -> 期望 `AuditChainBroken`
- [x] 反例 4：非回环建服务无 token -> 期望 `ValueError`
- [x] 反例 5：无 token 投递事件 -> 期望 401 和 `AuditSinkUnavailable`

## 契约

```python
class AuditRecord(BaseModel):
    event: AuditEvent
    prev_hash: str   # 空串表示租户链第一条
    hash: str        # sha256(prev_hash + canonical(event))
```

- `POST /v1/events` 请求体是 `AuditEvent`，成功返回 202 `{"hash": "..."}`。
- 写入失败返回 502 `{"error": "audit_write_failed"}`。
- `GET /healthz` 开放，其他路径要 bearer token。
- `AuditPipeline(path).append(event)` 返回 `AuditRecord`。
- `AuditPipeline` 启动时读文件重建每个租户的最后哈希。
- `verify_audit_file(path)` 返回记录数，断链抛 `AuditChainBroken(index, tenant)`。
- `HttpAuditSink(base_url, *, auth_token, client=None, timeout=10.0)` 的 `emit` 非 202 抛 `AuditSinkUnavailable`。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件、租户、输入输出哈希、链路哈希、token。
2. **调用方**：模型网关、工具网关、运行时、控制台。
3. **信任边界**：HTTP 网络、审计文件、写入进程。
4. **恶意输入最坏结果**：匿名注入伪造事件；篡改历史掩盖行为；多写者交错破坏链；审计服务不可用导致无痕运行。用鉴权、链校验、单写者约束、调用方拿到错误处理。
5. **失败是否泄露信息**：502 只给固定错误码。校验失败只给下标和租户，不回显事件内容。

### 已知边界

- JSONL 单进程追加。多副本同时写同一文件不安全，生产需要单写者或换存储。
- 没有签名，链只证明内部一致。
- 没有日期分区、轮转、保留期和集中投递。
- 审计服务不可用时是否阻塞业务由装配决定，默认把错误抛给调用方。
- CI 不跑 Postgres 之外的额外服务；审计服务测试用进程内 ASGI。

## 证据

- 反例红: `ImportError: cannot import name 'AuditPipeline' from 'adk_agent.audit'`，2 个测试模块收集失败
- 实现后绿: 审计管线与客户端 13 passed
- 真实服务: 投递 3 条事件（t1 两条、t2 一条），`verify-audit` 输出 ok 3 records
- 篡改第 2 条后 `verify-audit` 输出 `audit chain broken at record 1 for tenant 't1'`，退出 1
- `check.py --fast` -> 345 passed, 2 skipped，7 步全 PASS
- `check.py --full` -> 345 passed, 2 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-035-audit-pipeline.txt`
