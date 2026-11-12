# ADR-0003 A2A 消费方与提供方保持可选

状态: Proposed   日期: 2026-11-12   签字: 待 Jie CAO 确认

## 背景

ADR-0002 Phase 4 要求评估 A2A 的消费方和提供方。ADK 2.14 自带两条路径。

- 提供方：`google.adk.a2a.utils.agent_to_a2a.to_a2a(agent, ...)` 返回一个 Starlette 应用。
- 消费方：`RemoteA2aAgent(name, agent_card, ...)` 把远端 agent 当本地 agent 用。

两条路径都需要 `a2a` 这个 ADK extra。ADK 2.14 的 extra 固定 `a2a-sdk[http-server]>=0.3.4,<2`。本地实测安装会带进 `json-rpc`、`proto-plus`、`google-api-core`。

评估结论：

- `to_a2a` 的 `security_schemes` 只写进 agent card 元数据，文档明确说明运行时不强制。
- 默认暴露 agent card 和 JSON-RPC，没有内置鉴权。裸用等于把 agent 能力公开。
- 消费方没有按租户或 peer 的身份，只有共享 token 或自定义 httpx 客户端。

## 决定

1. A2A 适配器保持可选。代码惰性导入，未安装时抛 `A2aUnavailable` 并给出安装提示。默认依赖不变。
2. 提供方必须经过我们的 bearer 中间件。agent card、`/healthz`、JSON-RPC 全部要 token。
3. 非回环地址没有 token 一律拒绝启动，沿用 MCP HTTP 的规则。
4. 消费方带 token 时用一个设置了 `Authorization` 的 httpx 客户端，card 拉取和调用共用。
5. 不把 `a2a-sdk` 写进 `pyproject.toml`。等出现真实 peer、并且本 ADR 被确认后，再加 `a2a` extra。
6. `exposure="a2a"` 目前只是声明。按版本解析和网关排在 M5。

## 后果

- 默认安装和 CI 不增加依赖。需要 A2A 的环境自行安装。
- 本地可以验证提供方和消费方，CI 跳过需要 extra 的用例。
- 单一共享 token，没有 per-peer 身份、速率限制和授权映射，沿用到后续切片。
- agent card 受 token 保护，第三方 A2A 客户端需要支持自定义 header。
