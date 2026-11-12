# SLICE-033 工具网关独立部署（M5-2）

状态: gated
依据: ADR-0002 第 5、9 条，ADR-0004

## 意图（要什么，不写怎么写）

沿用 ADR-0004 的拆分形态，把工具网关变成独立服务。

- 跨进程契约 `ToolGatewayRequest` = invocation + request + grants。
- 授权以 grant 数据过线，服务端用 `GrantPolicyEngine` 判定，调用方不自行放行。
- 服务无状态，鉴权，非回环无 token 拒绝启动。
- 策略拒绝和未注册工具映射 403，执行失败和不可序列化输出映射 502。
- 审计在服务进程写 JSONL。
- 调用方走 `HttpToolGateway`，从 `GrantPolicyEngine` 取 grants。
- CLI `serve-tool-gateway --tools FILE`，文件里是 tool_id 到 callable 或 `ToolSpec` 的映射。
- 这一刀不接 OIDC，不做工具注册表服务发现。

## 新增文件

- `src/adk_agent/tools/service.py`
- `src/adk_agent/tools/http_gateway.py`
- `tests/tools/test_tool_service.py`
- `tests/tools/test_http_tool_gateway.py`
- `docs/contracts/tool_gateway_request.schema.json`
- `docs/evidence/SLICE-033-tool-gateway-service.txt`

## 修改文件

- `src/adk_agent/core/tool.py`：`ToolGatewayRequest`
- `src/adk_agent/core/__init__.py`：导出
- `src/adk_agent/tools/policy.py`：`GrantPolicyEngine.grants`
- `src/adk_agent/tools/__init__.py`：导出客户端与服务构造
- `src/adk_agent/cli.py`：`serve-tool-gateway`、`_load_tools`
- `scripts/export_contracts.py`：导出新 schema
- `docs/contracts/cli.md`：新命令
- `docs/specs/ROADMAP.md`：M5 进度

## 完成判据（可执行）

- [x] 契约往返 -> `tests/tools/test_tool_service.py::test_request_contract_roundtrip`
- [x] 服务无 token 拒绝网络绑定 -> `::test_network_bind_requires_token`
- [x] `/healthz` 开放，`/v1/invoke` 要 token -> `::test_healthz_open_and_invoke_protected`
- [x] 正常调用返回输出与数据类 -> `::test_invoke_returns_output`
- [x] 无 grant 拒绝 -> `::test_denied_grant_maps_to_403`
- [x] 未注册工具拒绝 -> `::test_unknown_tool_maps_to_403`
- [x] 输出不可序列化映射 502 -> `::test_unserializable_output_maps_to_502`
- [x] 客户端往返 -> `tests/tools/test_http_tool_gateway.py::test_client_roundtrip`
- [x] 客户端映射拒绝 -> `::test_client_maps_denial`
- [x] 客户端错误 token -> `::test_client_rejects_bad_token`
- [x] 不可序列化的 policy 抛错 -> `::test_client_rejects_opaque_policy`
- [x] 工具文件加载 -> `::test_load_tools_accepts_callables_and_specs`
- [x] 契约 schema 同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools.http_gateway import HttpToolGateway` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.core import ToolGatewayRequest` -> 当前 `ImportError`
- [x] 反例 3：非回环地址建服务无 token -> 期望 `ValueError`
- [x] 反例 4：无 token 调用 `/v1/invoke` -> 期望 401
- [x] 反例 5：任意 policy 引擎过线 -> 期望 `ToolGatewayError`

## 契约

```python
class ToolGatewayRequest(BaseModel):
    invocation: Invocation
    request: ToolRequest
    grants: list[ToolGrant]
```

- `POST /v1/invoke`，请求体是 `ToolGatewayRequest`，响应是 `ToolResponse`。
- 403 `{"error": "tool_denied"}`，502 `{"error": "tool_call_failed"}` 或 `{"error": "tool_output_invalid"}`。
- `GET /healthz` 返回 `{"status": "ok"}`，不需要 token。其他路径要 bearer token。
- `build_tool_gateway_app(gateway, *, host, auth_token, allow_unauthenticated)` 先走 `resolve_http_auth`。
- `HttpToolGateway(base_url, *, auth_token, client=None, timeout=60.0)` 从 `policy.grants` 取授权。
- 不可读取 grants 的 policy 引擎直接抛 `ToolGatewayError`，不发请求。

## 5 问威胁建模（10 分钟）

1. **数据**：工具参数、工具输出、数据分级、grant、token。
2. **调用方**：运行时 worker、编排器、控制台。
3. **信任边界**：HTTP 网络、bearer token、工具实现、审计文件。
4. **恶意输入最坏结果**：匿名调用工具；伪造 grants 越权；工具抛异常回显内部信息；输出不可序列化导致 500 泄露栈；大参数打爆内存。用强制鉴权、服务端判定、通用错误体、序列化失败统一 502 处理。
5. **失败是否泄露信息**：403 和 502 只给固定错误码。审计只写参数哈希、数据分级、输出哈希。

### 已知边界

- 服务信任调用方送来的 grants，per-caller 权威要等身份映射。
- 工具实现必须 JSON 可序列化输出。不可序列化按失败处理。
- 输出不可序列化时工具已经执行，审计已记为 ok；HTTP 返回 502。调用方要按未知结果重试前先确认幂等。
- 服务没有请求大小上限和速率限制。
- 没有工具注册表服务发现，工具在启动时由文件注册。
- JSONL 审计单进程，没有轮转。
- `GatewayLlm` 式的 ADK 工具守卫还没切到 HTTP 网关。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.tools.http_gateway'`，2 个测试模块收集失败
- 实现后绿: 服务与客户端测试 14 passed
- 真实服务: `/healthz` 200；add 返回 5；无 grant 和需审批工具都返回 ToolDenied；错误 token 401
- 审计文件: 3 条 tool.call，分别是 ok、policy_denied、approval_required（带 confidential 数据类）
- `check.py --fast` -> 325 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 325 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-033-tool-gateway-service.txt`
