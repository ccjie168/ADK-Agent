# SLICE-006 鉴权下沉到 builder

状态: merged

## 意图（要什么，不写怎么写）

`build_http_app` / `build_console_app` 是可直接调用的构造入口，鉴权策略必须在这里生效，
而不是只在 `run_*` 里检查。builder 构造前调用 `resolve_http_auth`：无 token 且未显式
允许 loopback 匿名时直接 `ValueError`；公开地址匿名绑定仍被拒绝。

## 完成判据（可执行）

- [x] 判据 1：`build_http_app(server, auth_token=None)` 抛 ValueError -> `tests/test_auth_builders.py::test_http_builder_requires_auth`
- [x] 判据 2：非 loopback 上 `allow_unauthenticated=True` 抛 ValueError -> `::test_http_builder_rejects_open_public_bind`
- [x] 判据 3：`build_console_app(agents, auth_token=None)` 抛 ValueError -> `::test_console_builder_requires_auth`
- [x] 判据 4：loopback + `allow_unauthenticated=True` 两处均可构造，控制台 `/api/agents` 返回 200 -> `::test_builders_allow_unauthenticated_on_loopback`
- [x] 判据 5：既有 401 断言保持 -> `tests/test_http_auth.py`、`tests/test_console.py`、`tests/test_deploy.py`

## 反例（必须在实现前跑红）

- [x] 反例 1：`build_http_app(server, auth_token=None)` -> 期望 ValueError；红色时 `DID NOT RAISE ValueError`
- [x] 反例 2：`build_http_app(..., allow_unauthenticated=True, host="0.0.0.0")` -> 期望 ValueError；红色时 `TypeError: ... unexpected keyword argument 'allow_unauthenticated'`
- [x] 反例 3：`build_console_app(agents, auth_token=None)` -> 期望 ValueError；红色时 `DID NOT RAISE ValueError`
- [x] 反例 4：loopback 匿名构造 -> 红色时 `TypeError`，因 builder 尚不接收该参数

## 契约（如涉及对外接口）

- `build_http_app(..., host="127.0.0.1", allow_unauthenticated=False)`；解析出的 token 非空才挂 `BearerAuthMiddleware`
- `build_console_app(..., host="127.0.0.1", allow_unauthenticated=False)`；同上
- `run_http` / `run_console` 行为不变，把 host / allow 透传给 builder

## 5 问威胁建模（10 分钟）

1. **数据**：MCP 工具调用与聊天内容。
2. **调用方**：`run_*`，以及任何直接构造 app 的嵌入代码。
3. **信任边界**：网络请求进入 app；builder 是最后一个能拒绝不安全配置的位置。
4. **恶意输入最坏结果**：公开地址无 token 启动 -> 反例 1、2 直接拒绝。
5. **失败是否泄露信息**：只抛配置错误，不包含 token。

## 证据

- 反例红: `pytest tests/test_auth_builders.py -q` -> `4 failed`（两条 `DID NOT RAISE ValueError`，两条 `TypeError: ... unexpected keyword argument 'allow_unauthenticated'`）
- 实现后绿: `pytest tests/test_auth_builders.py tests/test_http_auth.py tests/test_console.py tests/test_deploy.py -q` -> `16 passed`
