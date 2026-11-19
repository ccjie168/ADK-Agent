# SLICE-186 模型别名路由器与降级

状态: gated
依据: ADR-0033（Accepted 2026-11-19）决定 2/3 / slice 2：alias → 有序候选（primary + fallback），主候选
故障时路由到下一候选；`provider_allowlist` 保留为路由器之下的硬门；候选的数据分类准入被执行。

## 意图

1. `models/routing.py` 新增 `resolve_candidates(policy, alias, data_classes)`：按 alias 取有序候选，
   过滤掉不在 `provider_allowlist` 中的 provider，以及 `allowed_data_classes` 非空且不包含请求数据分类的候选。
2. 未知 alias 或无可放行候选抛 `ModelDenied`。
3. `PolicyModelGateway.complete` 增加可选 `alias`/`data_classes`：给 alias 时按序尝试候选，主候选抛错时降级到
   下一候选；全部失败抛 `ModelUnavailable`。策略拒绝（`ModelDenied`）不降级，直接上抛。
4. 不给 alias 时行为与现状完全一致。

## 契约（先改）

- 无对外 schema 变更（路由为网关内部行为）。

## 完成判据

- [ ] 候选按允许清单过滤并保序 -> `test_resolve_candidates_filters_allowlist`
- [ ] 数据分类准入过滤 -> `test_resolve_candidates_filters_data_classes`
- [ ] 未知 alias 拒绝 -> `test_resolve_unknown_alias_denied`
- [ ] 无放行候选拒绝 -> `test_resolve_no_permitted_candidate_denied`
- [ ] 网关按 alias 选主候选 -> `test_gateway_routes_alias_to_primary`
- [ ] 主候选失败降级到后备 -> `test_gateway_falls_back_to_next_candidate`
- [ ] 策略拒绝不降级 -> `test_policy_denial_does_not_fall_over`
- [ ] 全部候选失败抛 unavailable -> `test_gateway_all_candidates_fail`
- [ ] 直接 provider/model 路径不变 -> `test_direct_path_unchanged`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `models/routing.py`，网关不接受 `alias` 参数（TypeError）

## 5 问威胁建模

1. **数据**：模型别名、候选端点、请求的数据分类。
2. **调用方**：模型网关（`/v1/complete`、进程内网关）。
3. **信任边界**：manifest 路由策略到实际 provider 调用。
4. **恶意输入最坏结果**：受限数据被降级到未批准端点（缓解：候选准入在每次尝试前过滤；降级只发生在
   同一 alias 的已放行候选之间）。
5. **失败是否泄露信息**：错误仅 `ModelDenied`/`ModelUnavailable`，不泄露候选清单内容。

## 范围外

- 预算执行（slice 3）。
- 审计字段扩展：alias、实际模型、降级次数（slice 4）。
- 网关 HTTP 请求体按 alias 调用（后续接线）。

## 证据

- `docs/evidence/SLICE-186-model-router.txt`
