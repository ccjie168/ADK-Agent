# ADR-0005 运行时 worker 横向扩容靠外部化状态

状态: Proposed   日期: 2026-11-12   签字: 待 Jie CAO 确认

## 背景

ADR-0002 第 8 条说迁移前必须把状态外部化到 Postgres、对象存储、队列，本地盘不存状态。第 9 条把运行时 worker 排在两个网关之后。

现状：会话默认在进程内存，`SESSION_DB` 用 SQLite。两个副本各自持有会话，同一会话换一个副本就断。这不能算横向扩容。

## 决定

1. worker 无状态。会话存 Postgres，用 ADK 的 `DatabaseSessionService`。
2. 新增 `SESSION_URL` 选择共享会话存储。`memory://` 和未设置走内存；`postgresql+asyncpg://` 或 `postgresql://` 走 Postgres。
3. `SESSION_DB`（SQLite）保留为单节点演示路径。共享存储优先于它。
4. 驱动依赖不写进默认依赖。用户按需 `pip install "sqlalchemy[asyncio]>=2" asyncpg`。缺驱动时抛 `SessionStoreUnavailable` 并给安装命令。
5. 副本间不共享进程内配额和 RBAC 状态。配额共享后端仍待后续切片。
6. 保留 `/healthz`。数据库就绪探测等 ADK 暴露引擎后再做。
7. 优雅停机交给 uvicorn 的 SIGTERM 处理，不引入 K8s API 调用。

## 后果

- 同一会话可以在任意副本继续，前提是都指向同一个 `SESSION_URL`。
- 多副本部署必须用 Postgres，SQLite 只用于单节点演示。
- `SESSION_URL` 的驱动是可选依赖，CI 不装，相关用例按条件跳过。
- 配额和灰度状态仍是单进程，多副本下各自限额。这条要在共享配额切片里解决。
