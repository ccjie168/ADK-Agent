# SLICE-002 容器化与 Cloud Run 部署

状态: merged

## 意图（要什么，不写怎么写）

把 MCP HTTP 服务打成容器，可在 Cloud Run 运行：

- 绑定 `0.0.0.0`，读取平台注入的 `$PORT`；
- 必须带 Bearer token（CP-S6），无 token 拒绝启动；
- 提供 `/healthz` 供平台健康检查（无敏感信息、无需鉴权，显式声明为例外，
  用 MCP SDK 的 `custom_route` 实现）；
- 非 root 运行；镜像不含 `.venv` / 密钥。

本切片不执行真实 Cloud Run 部署（本机无 `gcloud` / GCP 凭据），交付可执行的
部署文档与命令；容器在本地 Docker 上做端到端验收。

## 完成判据（可执行）

- [x] 判据 1：`resolve_port(None)` 在 `PORT=8080` 时返回 8080，未设置时返回 8000；
      显式 port 优先；非法 `PORT` 抛 `ValueError`
      -> `tests/test_deploy.py::test_resolve_port`
- [x] 判据 2：`GET /healthz` 无鉴权返回 200 `{"status":"ok"}`；同一 app 上
      `POST /mcp` 无 token 仍 401
      -> `tests/test_deploy.py::test_healthz_open_mcp_protected`
- [x] 判据 3：`/healthz` 响应只有 `status` 字段，不泄露内部信息
      -> `tests/test_deploy.py::test_healthz_has_no_extra_fields`
- [x] 判据 4：`docker build` 成功；容器以非 root 用户运行
- [x] 判据 5：容器设 `PORT` 后监听该端口；`/healthz` 200；无 token `/mcp` 401；
      带 token `initialize` / `list_tools` 成功（容器端到端）
- [x] 判据 6：容器未设 `ADK_MCP_AUTH_TOKEN` 且未设 `ALLOW_UNAUTHENTICATED` 时
      以非 0 退出码拒绝启动
- [x] 判据 7：提供 `deploy/cloudrun.md`（gcloud 命令 + Secret Manager 注入 token）
- [x] 判据 8：`check.py --fast` 与 `--full` 全绿

## 反例（必须在实现前跑红）

- [x] 反例 1：`GET /healthz` -> 当前 404（没有健康路由）
- [x] 反例 2：`PORT=8080` 时服务仍用 8000（当前 CLI 固定默认 8000，不读 `PORT`）
- [x] 反例 3：容器无 token 启动 -> 期望非 0 退出（实现后必须成立）
- [x] 反例 4：容器内 `/mcp` 无 token -> 期望 401（不是 200/非 401 的 4xx）

## 契约（如涉及对外接口）

- 健康检查：`GET /healthz` -> `200` `{"status":"ok"}`（无鉴权，无数据）
- MCP：`POST /mcp` -> 需 `Authorization: Bearer <token>`
- 配置：`PORT`（平台注入，缺省 8000）、`ADK_MCP_AUTH_TOKEN`（HTTP 必需）、
  `ALLOW_UNAUTHENTICATED`（仅本地 loopback dev）

## 5 问威胁建模（10 分钟）

1. **数据**：agent 输入/输出含内部代码与配置；不含生产 PII（见 ADR-0001）。
2. **调用方**：Claude Code / 远端 MCP 客户端；平台健康检查。
3. **信任边界**：公网/负载均衡 -> 容器，必须 token；健康检查是显式例外。
4. **恶意输入最坏结果**：未鉴权调用可驱动 agent 调用工具 -> 401 反例。
5. **失败是否泄露信息**：401 与 healthz 都不返回 token、路径或内部细节。

## 证据

- **反例红（实现前）**：`pytest tests/test_deploy.py` ->
  `ImportError: cannot import name 'resolve_port'`。
- **实现后绿**：
  - `pytest tests/test_deploy.py` -> 3 passed；全量 `pytest` -> 14 passed
  - `check.py --fast` / `--full` -> ALL PASS
  - **容器端到端**（Docker 29.7.2，`scripts/smoke_container.py`）：
    - `docker build` 成功
    - `GET /healthz` -> `200`
    - 无 token `POST /mcp` -> `401`
    - 带 token `list_tools` -> `['minimal_agent']`
    - `id -u` -> `10001`（非 root）
    - 未设 `ADK_MCP_AUTH_TOKEN` -> 退出码 `1`（拒绝启动）
    - 输出：`ALL PASS`

## 备注

- `docker/dockerfile:1` 前端镜像在本网络不可拉取，已移除可选的 `# syntax`
  指令；基础镜像做成 `ARG PYTHON_IMAGE`，默认 `python:3.13-slim`。
- 运行时依赖尚未锁定；锁文件与 SBOM 留到 CI/SBOM 切片（CP-S4）。
- `scripts/smoke_container.py` 打印命令时对 `*TOKEN*` / `*KEY*` 值脱敏（CP-D2）。
