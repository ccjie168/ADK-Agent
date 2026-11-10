# SLICE-004 私有 Web 控制台（带鉴权）

状态: planned

## 意图（要什么，不写怎么写）

给私有部署提供一个最小可用的 Web 控制台，让人在浏览器里选择 agent、发消息、看回复，
不依赖 Claude Code CLI：

- 复用已有 Bearer 鉴权（CP-S6）：`/api/*` 必须带 token；
- `/healthz` 供探针；`/` 只返回静态页面（不含数据），浏览器首个导航无需 token；
- 复用 `Runner` 与会话服务（`SESSION_DB` 可持久化）；
- 作为独立服务进 `docker-compose.yml`，与 MCP 服务并列。

不做：多用户账号体系、SSO、前端构建链。token 由用户在页面输入，存于
`sessionStorage`，仅当前标签页有效。

## 完成判据（可执行）

- [ ] 判据 1：`build_console_app` 下 `/healthz` 与 `/` 无需 token 返回 200
      -> `tests/test_console.py::test_healthz_and_index_open`
- [ ] 判据 2：`/api/agents`、`/api/chat` 无 token 返回 401
      -> `::test_api_requires_token`
- [ ] 判据 3：带 token 的 `/api/agents` 返回 agent 列表（name + description）
      -> `::test_agents_with_token`
- [ ] 判据 4：`/api/chat` 对缺失 message / 未知 agent 返回 400
      -> `::test_chat_validates_input`
- [ ] 判据 5：CLI 提供 `adk-agent console --agents <file>`
- [ ] 判据 6：`docker compose config` 有效，且含 `adk-console` 服务
- [ ] 判据 7：`check.py --fast` 与 `--full` 全绿

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.console import build_console_app` -> `ImportError`
- [ ] 反例 2：`/api/agents` 无 token -> 期望 401（实现后必须成立）
- [ ] 反例 3：未知 agent 的 `/api/chat` -> 期望 400，而不是 500
- [ ] 反例 4：`adk-agent console ...` -> argparse 不认识该子命令

## 契约（如涉及对外接口）

- `GET /healthz` -> 200 `{"status":"ok"}`（开放，无数据）
- `GET /` -> 200 静态 HTML（开放，无数据）
- `GET /api/agents` -> 200 `[{name, description}]`（Bearer）
- `POST /api/chat` `{agent, message, session_id?}` -> 200 `{session_id, reply}`（Bearer）
  - 缺失 message / 未知 agent -> 400；agent 运行异常 -> 500（不返回内部细节）

## 5 问威胁建模（10 分钟）

1. **数据**：聊天可驱动 agent 的工具（读文件等），会话历史敏感。
2. **调用方**：私有网络内的团队成员，通过浏览器。
3. **信任边界**：浏览器 -> 控制台；必须 token，必须 TLS（反代）。
4. **恶意输入最坏结果**：无 token 调用可驱动工具 -> 401 反例；XSS 通过
   用户输入注入 -> 前端只用 `textContent`，不解析 HTML。
5. **失败是否泄露信息**：401/500 只返回通用错误，不返回内部路径或异常文本。

## 证据

- **反例红（实现前）**：`pytest tests/test_console.py` ->
  `ModuleNotFoundError: No module named 'adk_agent.console'`。
- **实现后绿**：
  - `pytest tests/test_console.py` -> 4 passed；全量 `pytest` -> 22 passed
  - `docker compose config -q` -> valid（含 `adk-console` 服务）
  - 控制台端到端（CLI 启动 `examples/minimal/agent.py`）：
    - `GET /healthz` -> 200
    - `GET /` -> 200，含 “ADK Console”
    - `GET /api/agents` 无 token -> 401；带 token -> 200
    - `POST /api/chat` 第 1 轮 -> 200，返回时间
    - `POST /api/chat` 同一 `session_id` 第 2 轮 -> 200，正确回忆上一问
    - `SESSION_DB` 文件已创建
  - `check.py --fast` / `--full` -> ALL PASS

## 备注（DeepSeek 多轮兼容性）

DeepSeek 的 Anthropic 兼容端点会拒绝历史里的 `redacted_thinking` 块，导致同一
session 的第 2 轮返回 422。已加入 `disable_thinking()`（`thinking_budget=0`）并在
两个示例的 agent 上启用；关闭 thinking 后多轮正常。用户自建 agent 若走该端点，
需同样设置 `generate_content_config=disable_thinking()`。
