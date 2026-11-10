# SLICE-003 私有部署：Docker Compose + 会话持久化

状态: planned

## 意图（要什么，不写怎么写）

让服务可在私有环境运行，不依赖 `gcloud` / GCP：

- 容器接受 `SESSION_DB`，用 `SqliteSessionService` 持久化会话（单机，卷挂载）；
- 提供 `build_runner(agent, session_db)`，CLI 增加 `--session-db`（缺省读 `SESSION_DB`）；
- 提供 `docker-compose.yml`、`deploy/selfhosted.md`、可选 K8s 清单；
- 保持 SLICE-001/002 的 Bearer 鉴权与 `/healthz`。

多机/多实例用 Postgres（`DatabaseSessionService`，需 `google-adk[db]`）——本切片
只给文档与配置说明，不在本机实测。

## 完成判据（可执行）

- [ ] 判据 1：`build_runner(agent, None)` 返回 `None`（沿用内存默认）；
      `build_runner(agent, path)` 返回带 `SqliteSessionService` 的 Runner，并创建父目录
      -> `tests/test_session_persist.py::test_build_runner`
- [ ] 判据 2：SQLite 会话跨服务实例仍在（模拟重启）；内存会话会丢失（对照）
      -> `::test_sqlite_session_survives_restart` / `::test_in_memory_session_lost_on_restart`
- [ ] 判据 3：CLI `serve` / `serve-many` 接受 `--session-db`，未给时读 `SESSION_DB`
- [ ] 判据 4：容器设 `SESSION_DB=/data/sessions.db` 后 `/data` 可写；
      `healthz` 200、无 token 401、带 token `list_tools` 仍通过
- [ ] 判据 5：提供 `docker-compose.yml`、`deploy/selfhosted.md`、`deploy/k8s/`
      （Deployment / Service / Secret 示例 / PVC）
- [ ] 判据 6：`check.py --fast` 与 `--full` 全绿

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.factory import build_runner` -> `ImportError`（未实现）
- [ ] 反例 2：默认内存会话在“重启”后 `get_session` 返回 `None`（证明必须持久化）
- [ ] 反例 3：`adk-agent serve --session-db ...` -> argparse 不认识该参数
- [ ] 反例 4：容器 `/data` 不可写（当前 Dockerfile 未创建并授权 `/data`）

## 契约（如涉及对外接口）

- 配置：`SESSION_DB`（可选，SQLite 文件路径）；`--session-db` 覆盖
- 单机：SQLite + 数据卷；多机：Postgres + `DatabaseSessionService`
- 容器：非 root；`/data` 由 `app` 用户可写

## 5 问威胁建模（10 分钟）

1. **数据**：会话历史含内部代码/对话，SQLite 文件属于敏感数据。
2. **调用方**：同 SLICE-001/002。
3. **信任边界**：数据卷 / 宿主机文件系统。
4. **恶意输入最坏结果**：会话文件泄露 -> 对话历史外泄；缓解：卷权限收紧、
   不随镜像分发、备份加密。
5. **失败是否泄露信息**：无新增。

## 证据

- **反例红（实现前）**：`pytest tests/test_session_persist.py` ->
  `ImportError: cannot import name 'build_runner'`。
- **实现后绿**：
  - `pytest tests/test_session_persist.py` -> 3 passed；全量 `pytest` -> 17 passed
  - `adk-agent serve --help` 显示 `--session-db`
  - `docker compose config -q` -> valid
  - 容器端到端（`scripts/smoke_container.py`）-> ALL PASS：
    `healthz 200` / 无 token 401 / 带 token `list_tools` /
    非 root `uid=10001` / `SESSION_DB=/data/sessions.db` / `/data` 可写 /
    无 token 拒启动 `exit 1`
  - `check.py --fast` / `--full` -> ALL PASS

## 备注

- SQLite 持久化用“两个服务实例共用同一 DB 文件”模拟重启；内存服务在同一场景
  返回 `None`，作为对照证明必须持久化。
- 多机 Postgres（`DatabaseSessionService`）仅提供文档与示例，本机无 Postgres
  未实测。
- Ruff 0.17 会格式化 Markdown 代码块；`deploy/` 未被 `extend-exclude` 排除。
