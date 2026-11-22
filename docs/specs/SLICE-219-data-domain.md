# SLICE-219 数据领域维

状态: gated
依据: ADR-0038 MVP 第 3 项（数据领域维，与敏感度 `DataClass` 正交，租户可扩展）。

## 意图

1. 定义 `DataDomain`：一条数据的领域标注。`concept_id` 引用术语层概念（领域，租户可扩展），
   `sensitivity` 是平台固定的敏感度 `DataClass`，两者正交、独立标注。
2. `sensitivity` 只接受 `DataClass` 四值，缺省 `internal`；`concept_id` 是安全字符串，不限制在平台
   枚举（租户自定义领域）。
3. 语义层开始依赖 `core.policy.DataClass`，方向 `semantics → core`，符合 `.importlinter` 分层。

## 契约（先改）

- `docs/contracts/semantics.md` 新增「数据本体层」一节：`DataDomain` 形状、正交语义、默认敏感度。

## 完成判据

- [x] 默认敏感度 internal -> `test_data_domain_defaults_to_internal`
- [x] 非法敏感度拒绝 -> `test_data_domain_rejects_unknown_sensitivity`
- [x] 租户自定义领域 -> `test_data_domain_accepts_tenant_concept`
- [x] 领域与敏感度正交 -> `test_data_domain_orthogonal_axes`
- [x] 全量门禁通过

## 反例

- 基线 `ba2361a`：没有 `DataDomain`，四个用例 `ImportError`。
- 若 `sensitivity` 不限制在 `DataClass`，`test_data_domain_rejects_unknown_sensitivity` 失败。
- 若把领域写死成平台枚举，`test_data_domain_accepts_tenant_concept` 失败。

## 5 问威胁建模

1. **数据**：数据所属领域与敏感度。
2. **调用方**：能力映射（SLICE-220）、数据分块与工具的领域标注（后续）。
3. **信任边界**：企业自定义领域 → 平台安全分级。
4. **恶意输入最坏结果**：敏感度被租户自定义成任意值，绕过安全分级。缓解：敏感度保持平台固定枚举，
   租户只能自定义领域（`concept_id`），不能改敏感度语义。
5. **失败是否泄露信息**：校验错误只报字段与枚举值，不含数据内容。

## 范围外

- 能力映射（SLICE-220）、确定性路由（SLICE-221）。
- 把 `DataDomain` 接到 `RagChunk`/`ToolGrant` 等既有模型（后续切片）。
- 领域概念引用存在性校验（需要跨术语表，SLICE-220 起）。

## 证据

- `docs/evidence/SLICE-219-data-domain.txt`
