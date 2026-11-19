# SLICE-166 本地开发逃生门 --trust-caller-policy

状态: gated
依据: ADR-0028（Accepted 2026-11-19）决定 5：本地开发逃生门只允许 `--trust-caller-policy`（回环
地址），默认关闭，仅用于演示信任域。

## 意图

1. `serve-model-gateway` 与 `serve-tool-gateway` 新增 `--trust-caller-policy`，默认关闭。
2. 打开时（且未配置注册表），网关回退到信任请求体 `policy`/`grants`（SLICE-164/165 之前的
   行为），仅用于回环开发；缺请求体 policy/grants 仍 403。
3. 非回环地址打开 `--trust-caller-policy` 启动退出 1（对齐 `--allow-unauthenticated` 的回环约束）。
4. `--trust-caller-policy` 与 `--registry-url`/`--registry` 互斥（配置了注册表即走服务端解析）。

## 契约（先改）

- `docs/contracts/cli.md` 的 `serve-model-gateway` / `serve-tool-gateway` 段补 `--trust-caller-policy`。

## 完成判据

- [x] 模型网关 `--trust-caller-policy` 且无注册表时用调用方 policy -> `test_model_gateway_trust_caller_policy`
- [x] 工具网关 `--trust-caller-policy` 且无注册表时用调用方 grants -> `test_tool_gateway_trust_caller_policy`
- [x] 非回环地址打开 `--trust-caller-policy` 被拒 -> `test_trust_caller_policy_requires_loopback`
- [x] 全量门禁通过

## 反例

- [x] 基线（未实现）上无 `--trust-caller-policy`，无注册表的网关 fail-closed 403

## 5 问威胁建模

1. **数据**：请求体 `policy`/`grants` 作为本地演示信任域。
2. **调用方**：回环开发进程。
3. **信任边界**：`--trust-caller-policy` 只允许回环，非回环启动即拒。
4. **恶意输入最坏结果**：把逃生门带到共享网络（缓解：非回环启动退出 1，与 `--allow-unauthenticated`
   同一条约束）。
5. **失败是否泄露信息**：无新增错误面，缺 policy/grants 仍 403。

## 范围外

- 缓存、别名/路由、风险分级、写工具幂等（后续）。

## 证据

- `docs/evidence/SLICE-166-trust-caller-policy.txt`
