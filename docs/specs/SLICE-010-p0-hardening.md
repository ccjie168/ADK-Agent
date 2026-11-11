# SLICE-010 P0 加固（M0-3）

状态: gated
依据: ADR-0002 第 5、6 条，评审发现 2、4、5、6、8

## 意图（要什么，不写怎么写）

关闭评审里的 P0 项，全部是边界和可观测性修复。

- 配置在解析时拒绝未知字段，`expose` 必须指向已存在的 agent。
- 控制台遇到过期或不属于当前 agent 的 `session_id` 时创建新会话，不再返回不可恢复的 500。
- 控制台记录 agent 运行异常，不再吞掉堆栈。
- bearer token 使用常量时间比较。
- 切换 agent 时前端重置 `sessionId`。

## 新增文件

- `tests/test_config_strictness.py`
- `tests/test_console_hardening.py`

## 修改文件

- `src/adk_agent/config.py`
- `src/adk_agent/console.py`
- `src/adk_agent/mcp/http.py`

## 完成判据（可执行）

- [x] 四个配置模型拒绝未知字段 -> `tests/test_config_strictness.py::test_*_rejects_unknown_field`
- [x] `expose` 不在 `agents` 中时被拒绝 -> `::test_expose_must_exist`
- [x] 合法配置仍能加载 -> `::test_valid_config_still_loads`
- [x] 过期 `session_id` 被替换为新会话，返回 200 -> `tests/test_console_hardening.py::test_stale_session_is_replaced`
- [x] agent 运行异常返回 500 且记录堆栈 -> `::test_chat_failure_is_logged`
- [x] bearer token 使用 `secrets.compare_digest` -> 现有 `tests/test_http_auth.py::test_http_rejects_wrong_token` 继续通过
- [x] 切换 agent 时前端重置 `sessionId`

## 反例（必须在实现前跑红）

- [x] 反例 1：`ModelConfig(..., thinking_buget=0)` -> 当前被忽略，期望 `ValidationError` -> `test_model_config_rejects_unknown_field`
- [x] 反例 2：`McpServerConfig(..., tramsport="http")` -> 当前被忽略，期望 `ValidationError` -> `test_mcp_config_rejects_unknown_field`
- [x] 反例 3：`AgentConfig(..., instruciton="typo")` -> 当前被忽略，期望 `ValidationError` -> `test_agent_config_rejects_unknown_field`
- [x] 反例 4：`FrameworkConfig(..., expse="a")` -> 当前被忽略，期望 `ValidationError` -> `test_framework_config_rejects_unknown_field`
- [x] 反例 5：`FrameworkConfig(agents={}, expose="missing")` -> 当前通过，期望 `ValidationError` -> `test_expose_must_exist`
- [x] 反例 6：`/api/chat` 收到不存在的 `session_id` -> 当前原样返回，期望替换为新会话 -> `test_stale_session_is_replaced`
- [x] 反例 7：runner 抛异常 -> 当前返回 500 但无日志，期望 `caplog` 含堆栈 -> `test_chat_failure_is_logged`

## 契约

- `ModelConfig`、`McpServerConfig`、`AgentConfig`、`FrameworkConfig` 使用 `ConfigDict(extra="forbid")`。
- `FrameworkConfig.expose` 为 `None` 或 `agents` 中的键。
- `/api/chat` 收到 `session_id` 时先按所选 agent 的 `app_name` 查找。找不到就创建新会话并返回新 id。
- 运行异常以 `logger.exception` 记录 agent 名和 session id，响应仍是通用 500，不泄露内部错误。
- token 比较使用 `secrets.compare_digest`。

## 5 问威胁建模（10 分钟）

1. **数据**：配置字段、会话 id、bearer token、运行异常堆栈。
2. **调用方**：CLI 读取配置，浏览器调用控制台，MCP 客户端调用 HTTP。
3. **信任边界**：配置文件、HTTP 请求、浏览器输入。
4. **恶意输入最坏结果**：配置拼写错误导致静默使用默认值；伪造 session id 探测其他会话；超长 token 触发可观测的时间差。未知字段拒绝、按 agent 范围查找会话、常量时间比较分别处理。
5. **失败是否泄露信息**：500 响应只返回固定错误码，堆栈只进服务端日志。

## 证据

- 反例红: `pytest tests/test_config_strictness.py tests/test_console_hardening.py -q` -> `7 failed, 1 passed`
- 实现后绿: 同命令 -> 8 passed
- `check.py --fast` -> 54 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-010-p0-hardening.txt`
