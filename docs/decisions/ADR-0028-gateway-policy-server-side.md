# ADR-0028 网关策略服务端化：模型与工具网关不再信任请求体策略

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

模型网关 `models/service.py` 的 `/v1/complete` 从请求体 `ModelGatewayRequest.policy` 读策略，
再交给 `PolicyModelGateway.complete`（`models/gateway.py`）做 `check_provider(request.provider,
policy)`。工具网关 `tools/service.py` 的 `/v1/invoke` 从请求体 `ToolGatewayRequest.grants`
构建 `GrantPolicyEngine(call.grants)`（`core/tool.py:32`、`tools/policy.py:14`）。`bind_principal`
（`auth.py:85`）只校验 tenant 与 subject，不校验策略。

这意味着任何持有有效 token 的调用方都能自行放宽 provider allowlist 或自行授权工具，网关作为
统一控制点的作用被架空。沙箱的模型出口中介（ADR-0024）只防「误调用」，不防「被攻陷工件主动
改写自己的策略」。这是「谁能用什么模型、调用什么工具」的信任基础，必须先修。

## 决定

1. **模型网关按 `invocation.agent_ref` 从注册表读取 `manifest.model_policy`，不再信任请求体。**
   请求体的 `policy` 从线上契约移除；过渡期如保留，必须与注册表一致，不一致 403
   `policy_mismatch`。
2. **工具网关按 `(tenant, agent_ref.id, agent_ref.version, agent_ref.digest)` 从 `ToolGrantStore`
   读取授权，不再信任 `call.grants`。** 复用控制台 `install_declared_guards(..., overlay=...)`
   已有的服务端覆盖逻辑（`console.py:2745`）。
3. **fail-closed。** 注册表或授权存储不可达时返回 503，绝不回退到调用方自带策略；缺失记录
   视为拒绝（403）。
4. **策略缓存按 agent_ref 的 digest 绑定，带 TTL，跨版本/digest 不复用。** 缓存失效先于授权
   失败，避免「改完策略仍放行旧值」。
5. **本地开发逃生门。** 只允许 `--trust-caller-policy`（回环地址），默认关闭，仅用于演示信任域，
   不进共享网络与生产。

## 备选与否决

- **继续信任请求体**：最小改动但信任边界不成立；否决。
- **网关自己维护独立策略表**：引入第二套策略源，与 manifest 冲突；否决，注册表是唯一权威。
- **无缓存每次读注册表**：可用性正确但放大注册表压力；暂用带 digest 的短 TTL 缓存。

## 后果

- 注册表进入模型/工具调用的请求路径，成为可用性依赖，需要监控与超时（复用注册表客户端超时）。
- 线上契约变更：`docs/contracts/model_gateway_request.schema.json`、
  `docs/contracts/tool_gateway_request.schema.json` 先改，再改代码（CLAUDE.md）。
- 现有调用方（`models/http_gateway.py`、`tools/client.py`、`tools/http_gateway.py`）停止发送
  `policy`/`grants`，或服务端直接拒绝。
- 控制台进程内路径的工具侧已有 overlay，模型侧对齐同样逻辑。

## 切片（待确认后分配）

1. 契约变更：两个请求 schema 移除或标注 `policy`/`grants` 为服务端忽略。
2. 模型网关服务端解析 `model_policy` + digest 缓存 + fail-closed 测试。
3. 工具网关服务端解析 `ToolGrantStore` + 复用 overlay + fail-closed 测试。
4. 逃生门 `--trust-caller-policy`（回环）与文档。
