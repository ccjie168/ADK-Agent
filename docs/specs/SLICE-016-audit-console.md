# SLICE-016 审计闭环与控制台 v0（M1-5）

状态: gated
依据: ADR-0002 第 4、6 条

## 意图（要什么，不写怎么写）

让控制台产生并展示 run 级审计，形成第一个可见的平台界面。

- `ListAuditSink` 在内存里保留最近 N 条 `AuditEvent`。
- 控制台的每个 `AgentRuntime` 使用同一个 sink。
- 新增 `GET /api/audit?limit=50`，返回最近事件，受 bearer 鉴权保护。
- 页面增加 Recent audit 面板，显示 action、target、status、延迟、run_id、trace_id。
- 新增控制台 HTTP 契约文档。

## 新增文件

- `src/adk_agent/audit/__init__.py`
- `src/adk_agent/audit/memory.py`
- `tests/audit/test_memory_sink.py`
- `tests/test_console_audit.py`
- `docs/contracts/console.md`

## 修改文件

- `src/adk_agent/console.py`：接入 sink，新增 `/api/audit`，页面增加审计面板
- `.importlinter`：`core` 禁止导入 `adk_agent.audit`
- `docs/contracts/README.md`：登记 `console.md`
- `docs/specs/ROADMAP.md`：M1 增加 SLICE-016、SLICE-017

## 完成判据（可执行）

- [x] sink 保留最近 N 条，按时间顺序返回 -> `tests/audit/test_memory_sink.py::test_recent_returns_last_n`
- [x] `maxlen <= 0` 被拒绝 -> `::test_rejects_non_positive_maxlen`
- [x] 一次 chat 产生 `agent.run` 事件，run_id 与响应一致 -> `tests/test_console_audit.py::test_chat_writes_audit_event`
- [x] `/api/audit` 无 token 返回 401 -> `::test_audit_requires_token`
- [x] 页面包含 Recent audit 面板和刷新按钮

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.audit import ListAuditSink` -> 当前 `ModuleNotFoundError` -> sink 测试收集失败
- [x] 反例 2：`GET /api/audit` -> 当前 404 -> `test_audit_requires_token` 或 chat 测试失败
- [x] 反例 3：chat 后审计为空 -> 期望一条 `agent.run` -> `test_chat_writes_audit_event`

## 契约

```python
class ListAuditSink:
    def __init__(self, maxlen: int = 1000) -> None: ...
    async def emit(self, event: AuditEvent) -> None: ...
    def recent(self, limit: int = 50) -> list[AuditEvent]: ...
```

控制台 HTTP：

- `GET /api/audit?limit=50` -> `list[AuditEvent]`，按时间正序，最多 200 条，需要 bearer token。
- `POST /api/chat` 继续返回 `session_id`、`reply`、`run_id`、`trace_id`。
- `GET /` 和 `/healthz` 保持开放。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件，含 run_id、trace_id、principal、目标、状态、延迟。不含原始输入输出。
2. **调用方**：控制台浏览器、后续管理员界面。
3. **信任边界**：`/api/audit` 是受鉴权的 HTTP 端点。
4. **恶意输入最坏结果**：`limit` 过大导致内存或响应膨胀。上限 200。
5. **失败是否泄露信息**：事件不含 prompt 正文和密钥；401 不返回事件。

## 证据

- 反例红: audit 测试 `ModuleNotFoundError`；`GET /api/audit` 返回 404
- 实现后绿: 目标测试 4 passed
- `check.py --fast` -> 96 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-016-audit-console.txt`
