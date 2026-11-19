# SLICE-165 工具网关服务端授权

状态: gated
依据: ADR-0028（Accepted 2026-11-19）与 `docs/review/m6-enterprise-trust-chain.md` 的 Gate 2：
工具网关不再信任请求体 `grants`，按 `agent_ref` 从注册表解析 manifest `tool_grants`，并按
`ToolGrantStore` 读取临时授权。

## 意图

1. `ToolGatewayRequest.grants` 保留为可选（兼容旧调用方），但网关忽略它。
2. `build_tool_gateway_app` 新增 `grant_resolver`（按 agent_ref 从注册表解析 manifest
   `tool_grants`）与 `tool_grants`（`ToolGrantStore` overlay，复用控制台 `install_declared_guards`
   的 overlay 模式）。
3. `invoke()` 用 `GrantPolicyEngine(server_grants, overlay=tool_grants)` 决策，不再
   `GrantPolicyEngine(call.grants)`。
4. fail-closed：未配置 `grant_resolver` 或查不到记录 → 403 `grant_unavailable`；解析器抛异常
   （注册表/授权存储不可达）→ 503 `grant_store_unavailable`。
5. `serve-tool-gateway` 新增 `--registry-url`/`--registry`（manifest 授权权威）与
   `--tool-grants-dir`/`GRANT_URL`（临时授权 overlay，复用 `_tool_grant_store`）。

## 契约（先改）

- `docs/contracts/tool_gateway_request.schema.json`：`grants` 从 required 移除（当前为可选，
  需确认并标注服务端忽略）。

## 完成判据

- [x] 调用方伪造 grants 放行未声明工具被拒 -> `test_tool_gateway_ignores_caller_grants`
- [x] manifest 授权的工具正常放行 -> `test_tool_gateway_uses_manifest_grants`
- [x] 未配置授权权威时 fail-closed 403 -> `test_tool_gateway_fails_closed_without_resolver`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `build_tool_gateway_app` 用请求体 `call.grants` 决策，伪造 grants 即放行

## 5 问威胁建模

1. **数据**：manifest `tool_grants` 与临时授权 `ToolGrant`。
2. **调用方**：持有网关 token 的 Agent 运行时或沙箱工件。
3. **信任边界**：HTTP 请求体 `grants` → 网关服务端授权权威（注册表 + ToolGrantStore）。
4. **恶意输入最坏结果**：被攻陷工件自报 `["sap.write:*"]` 直接放行（缓解：服务端只信注册表
   与授权存储，缺权威 fail-closed）。
5. **失败是否泄露信息**：固定 403 `grant_unavailable` / 503 `grant_store_unavailable`。

## 范围外

- 逃生门 `--trust-caller-policy`（ADR-0028 slice 4）。
- 写工具幂等（ADR-0034）与风险分级（ADR-0029）。

## 证据

- `docs/evidence/SLICE-165-tool-gateway-server-grants.txt`
