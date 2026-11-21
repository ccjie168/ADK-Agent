# SLICE-205 执行模型 allowlist

状态: gated
依据: ADR-0033「后果」写明 `model_allowlist` 随该 ADR 落地执行；2026-11-21 复盘第 4 节第 2 条。

## 意图

1. `ModelPolicy.model_allowlist` 真正生效，而不是只在 manifest 里记录。
2. 语义：空列表表示不限制模型（兼容存量 manifest）；非空时请求的模型必须在列表里。
3. 直连请求与别名路由都执行：别名候选按模型过滤，过滤后没有候选按策略拒绝。
4. 拒绝走既有 `ModelDenied`，HTTP 仍映射 403 `model_denied`，审计 `error_code=model_not_allowed`。

## 契约（先改）

- manifest schema 不变；`docs/contracts/model_gateway_request.schema.json` 不变。
- ADR-0033 补一条落地记录：`model_allowlist` 已由 SLICE-205 执行，空列表语义写清。
- 已知边界：控制台/`build_model()` 直接访问供应商不经网关，allowlist 只约束网关路径；写进 ADR 与运维手册。

## 完成判据

- [x] 非空 allowlist 拒绝列表外模型 -> `test_direct_request_outside_model_allowlist_is_denied`
- [x] 非空 allowlist 放行列表内模型 -> `test_direct_request_inside_model_allowlist_is_served`
- [x] 空 allowlist 不限制模型 -> `test_empty_model_allowlist_admits_any_model`
- [x] 别名候选按 allowlist 过滤 -> `test_alias_candidates_are_filtered_by_model_allowlist`
- [x] 别名没有合法候选时拒绝 -> `test_alias_without_allowed_candidate_is_denied`
- [x] 拒绝审计带 `model_not_allowed` -> `test_denied_model_is_audited`
- [x] 全量门禁通过

## 反例

- [x] 基线：列表外模型被照常服务、别名不按模型过滤、拒绝无审计，实测 4 failed / 3 passed。
- [x] 若把空列表当“全部拒绝”，第三个用例失败（存量 manifest 默认空）。
- [x] 若只在直连路径过滤，别名用例失败。

## 5 问威胁建模

1. **数据**：manifest 的模型策略与网关请求里的 provider/model。
2. **调用方**：模型网关的 HTTP 调用方与别名路由。
3. **信任边界**：注册表 manifest → 网关策略。
4. **恶意输入最坏结果**：调用方绕过 allowlist 使用未批准模型，带来数据出境或成本。缓解：直连与别名
   两条路径都在调用供应商前检查；拒绝写审计；错误码可区分 provider 与 model。
5. **失败是否泄露信息**：拒绝信息只含策略原因，不含 prompt。

## 范围外

- 控制台 `build_model()` 直连供应商的路径，本轮不加中介。
- 每个别名的独立成本上限。

## 证据

- `docs/evidence/SLICE-205-model-allowlist.txt`
