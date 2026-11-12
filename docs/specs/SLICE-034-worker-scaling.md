# SLICE-034 运行时 worker 横向扩容（M5-3）

状态: gated
依据: ADR-0002 第 8、9 条，ADR-0005

## 意图（要什么，不写怎么写）

让多个 worker 副本可以服务同一个会话。

- `SESSION_URL` 选择共享会话存储。Postgres 走 ADK `DatabaseSessionService`。
- 共享存储优先于 `SESSION_DB` 的 SQLite 演示路径。
- 缺驱动时抛 `SessionStoreUnavailable`，带安装命令，不静默退回内存。
- 控制台、`serve`、`serve-many` 都走同一个会话存储工厂。
- 这一刀不共享配额和 RBAC 状态，也不加默认依赖。

## 新增文件

- `src/adk_agent/runtime/sessions.py`
- `tests/runtime/test_sessions.py`
- `docs/decisions/ADR-0005-worker-scaling.md`
- `docs/evidence/SLICE-034-worker-scaling.txt`

## 修改文件

- `src/adk_agent/runtime/__init__.py`：导出会话工厂
- `src/adk_agent/factory.py`：`build_runner` 走会话工厂
- `src/adk_agent/console.py`：`_session_service` 走会话工厂
- `src/adk_agent/cli.py`：`--session-db` 帮助文本提到 `SESSION_URL`
- `deploy/selfhosted.md`：`SESSION_URL` 多副本说明
- `docs/specs/ROADMAP.md`：M5 进度

## 完成判据（可执行）

- [x] 未配置时走内存 -> `tests/runtime/test_sessions.py::test_default_is_memory`
- [x] `memory://` 走内存 -> `::test_memory_scheme`
- [x] SQLite 演示路径可用 -> `::test_sqlite_path`
- [x] 非法 URL 拒绝 -> `::test_invalid_url_rejected`
- [x] 缺驱动给出安装提示 -> `::test_missing_driver_hint`
- [x] `SESSION_URL` 优先于 SQLite -> `::test_url_wins_over_sqlite`
- [x] 未配置外部存储返回 None -> `::test_no_external_store_returns_none`
- [x] 两个服务共享同一会话（需要 Postgres） -> `::test_two_workers_share_a_session`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.runtime.sessions import build_session_service` -> 当前 `ImportError`
- [x] 反例 2：`SESSION_URL=sqlite:///x` -> 期望 `ValueError`
- [x] 反例 3：缺 asyncpg 时构造 Postgres 存储 -> 期望 `SessionStoreUnavailable`
- [x] 反例 4：两个副本各自内存存储共享会话 -> 期望测试失败（当前行为）

## 契约

```python
class SessionStoreUnavailable(RuntimeError): ...

def build_session_service(*, url: str | None = None,
                          sqlite_path: str | None = None) -> Any: ...
def configured_session_service(session_db: str | None) -> Any | None: ...
```

- `url` 为空且无 sqlite 路径时返回 `InMemorySessionService`。
- `memory://` 返回 `InMemorySessionService`。
- `postgresql://` 归一化为 `postgresql+asyncpg://`，用 `DatabaseSessionService`。
- 其他 scheme 抛 `ValueError`，提示用 `--session-db` 做单节点演示。
- 导入 ADK 数据库会话服务失败时抛 `SessionStoreUnavailable`，带安装命令。
- `configured_session_service` 读 `SESSION_URL`，其次 `session_db`，都没有返回 `None`。

## 5 问威胁建模（10 分钟）

1. **数据**：会话历史、用户输入、工具输出、DSN 里的凭据。
2. **调用方**：控制台、MCP 服务、编排器、负载均衡后的任意副本。
3. **信任边界**：Postgres、DSN、副本进程。
4. **恶意输入最坏结果**：DSN 泄漏；副本连到错误库读到别人会话；两个副本各自内存导致会话漂移；缺驱动静默退回内存造成数据丢失。用环境变量、租户字段随会话走、显式失败处理。
5. **失败是否泄露信息**：`SessionStoreUnavailable` 只给安装命令。DSN 不写日志、不回显。连接失败交给 ADK 的异常。

### 已知边界

- 配额和 RBAC 仍是进程内，多副本各自计数。
- 没有数据库就绪探测，只有进程级 `/healthz`。
- 没有会话清理和保留期策略。
- 驱动不是默认依赖，CI 跳过 Postgres 用例。
- K8s 清单没有改副本数和反亲和，部署参数由使用者维护。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.runtime.sessions'`
- 实现后绿: 会话工厂 7 passed，1 skipped（未设 TEST_POSTGRES_URL）
- Postgres 实测: 设 TEST_POSTGRES_URL 后 8 passed，两个服务共享同一会话
- 双 worker 实测: 8083 建会话，8084 用同一 session_id 继续，返回同一会话；库里 4 条事件 user/agent 各两条
- `check.py --fast` -> 332 passed, 2 skipped，7 步全 PASS
- `check.py --full` -> 332 passed, 2 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-034-worker-scaling.txt`
