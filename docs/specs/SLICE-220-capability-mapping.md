# SLICE-220 能力映射

状态: gated
依据: ADR-0038 MVP 第 4 项（能力 id 关联 tool_grants / A2A skill，校验能力 id 不悬空）。

## 意图

1. 定义 `CapabilityBinding`：一个能力 id（`CapabilityId`）显式绑定到一个术语概念（`concept_id`）和一个
   具体工具（`tool_id`，对应 `tool_grants` 的 `tool_id` 或 A2A skill id）。
2. `validate_capability_bindings(bindings, concept_ids, tool_ids)` 做集合级校验：能力 id 唯一、
   概念引用存在、工具引用存在，任何悬空都 `ValueError`。
3. 能力 id 沿用 dot-namespaced 形状（SLICE-217），不另建能力模型，只做「能力 ↔ 概念 ↔ 工具」的对齐。

## 契约（先改）

- `docs/contracts/semantics.md` 的能力层补 `CapabilityBinding` 形状与不悬空校验。

## 完成判据

- [x] 合法绑定通过 -> `test_capability_binding_validates`
- [x] 能力 id 重复拒绝 -> `test_duplicate_capability_id_rejected`
- [x] 概念悬空拒绝 -> `test_missing_concept_rejected`
- [x] 工具悬空拒绝 -> `test_missing_tool_rejected`
- [x] 全量门禁通过

## 反例

- 基线 `a14c331`：没有 `CapabilityBinding` 与校验函数，四个用例 `ImportError`。
- 若校验不查工具引用，`test_missing_tool_rejected` 失败。

## 5 问威胁建模

1. **数据**：能力 id 到术语概念与具体工具的映射。
2. **调用方**：确定性路由（SLICE-221）、控制台能力视图。
3. **信任边界**：平台声明的能力 → 实际存在的工具。
4. **恶意输入最坏结果**：能力 id 指向不存在的工具，路由到「空气能力」，运行时报错或被伪造能力误导。
   缓解：声明即校验，悬空绑定 fail-closed 拒绝。
5. **失败是否泄露信息**：只报能力 id 与缺失的引用类型，不含工具实现。

## 范围外

- 确定性路由（SLICE-221）。
- 能力 id 与 A2A skill 具体字段（tags/examples）的完整映射（MVP 用 `tool_id` 作为统一锚点）。

## 证据

- `docs/evidence/SLICE-220-capability-mapping.txt`
