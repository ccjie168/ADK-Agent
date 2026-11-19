# SLICE-164 模型网关服务端策略解析

状态: gated
依据: ADR-0028（Accepted 2026-11-19）与 `docs/review/m6-enterprise-trust-chain.md` 的 Gate 3：
模型网关不再信任请求体 `policy`，按 `agent_ref` 从注册表解析 `manifest.model_policy`。

## 意图

1. `ModelGatewayRequest.policy` 改为可选（`policy: ModelPolicy | None = None`）；网关忽略调用方
   提供的 policy，服务端按 `invocation.agent_ref` 从注册表解析 `manifest.model_policy`。
2. `serve-model-gateway` 新增策略权威来源：`--registry-url`（`HttpAgentRegistry`）或
   `--registry`（`FileAgentRegistry`），与现有注册表客户端复用同一套参数语义。
3. fail-closed：未配置注册表或查不到 manifest → 403 `policy_unavailable`；注册表不可达 → 503
   `policy_store_unavailable`。
4. 策略缓存按 `agent_ref.digest` 绑定，带 TTL，跨版本/digest 不复用。
5. 工具网关的 `grants` 服务端化是下一刀（ADR-0028 slice 3），本刀只改模型网关。

## 契约（先改）

- `docs/contracts/model_gateway_request.schema.json`：`policy` 从 required 移除，改为可选。

## 完成判据

- [x] 调用方伪造 allowlist 放行未注册 provider 被拒 -> `test_gateway_ignores_caller_policy`
- [x] manifest 允许的 provider 正常放行 -> `test_gateway_uses_manifest_policy`
- [x] 未配置注册表时 fail-closed 403 -> `test_gateway_fails_closed_without_resolver`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上 `build_model_gateway_app` 用请求体 `call.policy` 决策，伪造 allowlist 即放行

## 5 问威胁建模

1. **数据**：`manifest.model_policy`（provider/model allowlist、预算）。
2. **调用方**：持有网关 token 的 Agent 运行时或沙箱工件。
3. **信任边界**：HTTP 请求体 `policy` → 网关服务端策略权威（注册表）。
4. **恶意输入最坏结果**：被攻陷工件自改 allowlist 调用未批准模型/数据分类（缓解：服务端只信
   注册表，缺权威 fail-closed）。
5. **失败是否泄露信息**：固定 403 `policy_unavailable` / 503 `policy_store_unavailable`，不泄露
   manifest 存在性。

## 范围外

- 工具网关 `grants` 服务端化（ADR-0028 slice 3，下一刀）。
- 逃生门 `--trust-caller-policy`（ADR-0028 slice 4）。
- 模型别名/路由/降级（ADR-0033，后续）。

## 证据

- `docs/evidence/SLICE-164-model-gateway-server-policy.txt`
