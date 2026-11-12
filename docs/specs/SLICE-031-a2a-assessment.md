# SLICE-031 A2A 消费方与提供方评估（M4-4）

状态: gated
依据: ADR-0002 第 4、5、6 条，ADR-0003

## 意图（要什么，不写怎么写）

补齐 M4 的最后一条，并收口 M4。

- 评估 ADK 2.14 的 A2A 提供方和消费方能力，结论写入 ADR-0003。
- 提供方适配器：把 ADK agent 变成 A2A Starlette 应用，再套我们的 bearer 中间件。
- 非回环地址没有 token 拒绝启动，沿用 MCP HTTP 规则。
- agent card 和 JSON-RPC 都要鉴权，不做匿名 card。
- 消费方适配器：构造 `RemoteA2aAgent`，可选带上 Authorization 的 httpx 客户端。
- 未安装可选依赖时抛 `A2aUnavailable`，提示安装命令。默认依赖不变。
- CLI 增加 `serve-a2a`。
- 这一刀不把 A2A 接入注册表版本解析，也不加默认依赖。

## 新增文件

- `src/adk_agent/a2a.py`
- `tests/test_a2a.py`
- `docs/decisions/ADR-0003-a2a-optional.md`
- `docs/evidence/SLICE-031-a2a-assessment.txt`
- `docs/evidence/M4-milestone.txt`

## 修改文件

- `src/adk_agent/cli.py`：`serve-a2a`
- `docs/contracts/cli.md`：`serve-a2a`
- `docs/specs/ROADMAP.md`：M4 收口

## 完成判据（可执行）

- [x] 网络绑定没 token 拒绝启动 -> `tests/test_a2a.py::test_network_bind_requires_token`
- [x] 缺可选依赖时给出安装提示 -> `tests/test_a2a.py::test_missing_extra_has_install_hint`
- [x] 缺依赖时构造消费方也提示 -> `tests/test_a2a.py::test_missing_extra_blocks_consumer`
- [x] agent card 需要 token -> `tests/test_a2a.py::test_agent_card_requires_token`
- [x] JSON-RPC 需要 token -> `tests/test_a2a.py::test_rpc_requires_token`
- [x] 带 token 能取到 card -> `tests/test_a2a.py::test_agent_card_with_token`
- [x] 消费方构造成功并带名称 -> `tests/test_a2a.py::test_remote_agent_constructs`
- [x] 真实提供方加消费方端到端 -> 手工验证，见 evidence

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.a2a import A2aUnavailable` -> 当前 `ImportError`
- [x] 反例 2：非回环地址无 token 启动 -> 期望 `ValueError`
- [x] 反例 3：A2A 应用匿名访问 agent card -> 期望 401
- [x] 反例 4：未安装依赖时仍尝试构造应用 -> 期望 `A2aUnavailable`

## 契约

```python
class A2aUnavailable(RuntimeError): ...

def build_a2a_app(agent, *, host="127.0.0.1", port=8000, rpc_path="",
                  runner=None, auth_token=None) -> Any: ...
def serve_a2a(agent, *, host="127.0.0.1", port=None, rpc_path="",
              runner=None, auth_token=None, allow_unauthenticated=False) -> None: ...
def remote_agent(name, agent_card, *, description="", timeout=600.0,
                 auth_token=None) -> Any: ...
```

- 惰性导入 `google.adk.a2a`，导入失败统一转成 `A2aUnavailable`。
- `build_a2a_app` 只在给了 token 时加 `BearerAuthMiddleware`，没有开放路径。
- `serve_a2a` 先调用 `resolve_http_auth`。非回环且无 token 抛 `ValueError`。
- `remote_agent` 在给了 token 时创建带默认 `Authorization` 头的 `httpx.AsyncClient`。
- 安装提示固定指向 ADK 声明的版本范围 `a2a-sdk[http-server]>=0.3.4,<2`。

## 5 问威胁建模（10 分钟）

1. **数据**：agent card（技能、端点）、JSON-RPC 消息、任务状态、peer token。
2. **调用方**：外部 A2A peer、控制台、编排器。
3. **信任边界**：A2A SDK、ADK 的 executor、网络对端、共享 token。
4. **恶意输入最坏结果**：匿名读 card 拿到能力清单；匿名发消息消耗模型额度；大 payload 打爆内存；远端返回恶意内容污染本地 agent。用全路径鉴权、沿用请求体上限边界、把远端输出当不可信输入处理。
5. **失败是否泄露信息**：401 只返回 `unauthorized`。`A2aUnavailable` 只给安装命令。

### 已知边界

- 单一共享 token。没有 per-peer 身份、作用域和速率限制。
- agent card 需要 token，部分第三方客户端默认匿名拉 card，需要手工配置 header。
- 没有接注册表版本解析和灰度，`exposure="a2a"` 只是声明。
- 消费方没有做响应内容清洗，远端输出按不可信输入对待。
- `a2a-sdk` 不在默认依赖，CI 跳过需要它的用例。

## 证据

- 反例红: `ModuleNotFoundError: No module named 'adk_agent.a2a'`，1 个测试模块收集失败
- 实现后绿: A2A 适配器 7 passed（本机装了 a2a-sdk）。CI 未装时 3 passed，4 skipped
- 真实提供方: 无 token 拉 card 返回 401；带 token 返回 200，card 名称 a2a_probe
- 真实消费方: RemoteA2aAgent 经 A2A 调用拿到 "hello from a2a provider"
- `check.py --fast` -> 299 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 299 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-031-a2a-assessment.txt`
