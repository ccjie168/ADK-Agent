# SLICE-185 模型别名与路由策略 schema

状态: gated
依据: ADR-0033（Accepted 2026-11-19）决定 1/2 / slice 1：manifest 增加 `model_alias`，alias 解析为
有序候选列表（primary + fallback），每个候选带 provider/model 与数据分类准入。本切片只落 schema 与契约，
路由器执行后置。

## 意图

1. `core/manifest.py` 新增 `ModelCandidate`（`provider`、`model`、`allowed_data_classes`）。
2. 新增 `ModelAlias`（`alias` + 有序 `candidates`，至少一个），`ModelPolicy` 增加 `model_aliases`（可空）。
3. `AgentManifest` 增加 `model_alias: str | None = None`。
4. `manifest_digest` 对缺省新字段保持向后兼容：`model_alias` 为 None、`model_aliases` 为空时从哈希载荷中剔除，
   存量记录 digest 不变。
5. 重生成 `manifest.schema.json`。

## 契约（先改）

- `docs/contracts/manifest.schema.json` 重生成（新增 `model_alias`、`model_policy.model_aliases`）。
- `docs/contracts/model_gateway_request.schema.json` 重生成（内嵌 `ModelPolicy`，同步新增 `model_aliases`）。

## 完成判据

- [ ] alias 与候选可构造 -> `test_manifest_accepts_model_alias_and_aliases`
- [ ] 候选列表不能为空 -> `test_model_alias_requires_candidates`
- [ ] 同一 alias 名重复被拒 -> `test_model_policy_rejects_duplicate_alias`
- [ ] 缺省新字段不改变存量 digest -> `test_manifest_digest_unchanged_by_defaults`
- [ ] 新字段参与 digest -> `test_manifest_digest_covers_model_alias`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `AgentManifest` 无 `model_alias`、`ModelPolicy` 无 `model_aliases`（extra_forbidden）

## 5 问威胁建模

1. **数据**：模型别名与候选端点（provider/model、数据分类准入）。
2. **调用方**：模型网关（后续按 alias 选路）、发布流程。
3. **信任边界**：manifest schema 到网关路由。
4. **恶意输入最坏结果**：受限数据被路由到未批准端点（缓解：候选带 `allowed_data_classes`，执行在 slice 2；
   本切片保证 schema 承载该信息且 digest 绑定）。
5. **失败是否泄露信息**：纯 schema 校验，无新错误面。

## 范围外

- 路由器与 fallback 执行（slice 2）。
- 预算执行（slice 3）。
- 审计字段扩展（slice 4）。

## 证据

- `docs/evidence/SLICE-185-model-alias-schema.txt`
