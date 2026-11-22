# SLICE-217 语义层核心数据模型

状态: gated
依据: ADR-0038 MVP 第 1 项（语义层核心数据模型）。

## 意图

1. 定义语义层的声明式类型：术语层（`Term`/`Concept`/`ConceptScheme`/`ConceptMapping`）与能力层
   （`CapabilityId`），纯数据、无 I/O、无 adapter 依赖。
2. 校验规则落在模型与 `ConceptScheme` 上：标签唯一、层级无环、映射两端存在、`exact` 映射一致。
3. 分层边界：新包 `adk_agent.semantics` 依赖 `core`，`core` 不得反向依赖它（写入 `.importlinter`）。

## 契约（先改）

- 新增 `docs/contracts/semantics.md`，记录类型形状与校验规则。

## 完成判据

- [ ] 每语言一个首选标签 -> `test_concept_rejects_duplicate_pref_label_in_language`
- [ ] 层级关系不能成环 -> `test_scheme_rejects_cycle_in_broader`
- [ ] 映射两端必须存在 -> `test_scheme_rejects_dangling_mapping`
- [ ] `exact` 映射一致 -> `test_scheme_rejects_conflicting_exact_match`
- [ ] 能力 id 合法形状 -> `test_capability_id_accepts_dot_namespaced`
- [ ] 能力 id 非法形状 -> `test_capability_id_rejects_bad_shape`
- [ ] 全量门禁通过

## 反例

- 基线 `c6893bc`：没有 `adk_agent.semantics` 包，六个用例全部 `ImportError`。
- 若只校验标签唯一不做层级无环，`test_scheme_rejects_cycle_in_broader` 失败。
- 若 `exact` 与 `broad` 映射共存不拒绝，`test_scheme_rejects_conflicting_exact_match` 失败。

## 5 问威胁建模

1. **数据**：企业术语、概念层级、概念间映射、能力标识。
2. **调用方**：registry 存储、编排路由、控制台展示（后续切片）。
3. **信任边界**：企业自定义的语义声明 → 平台路由与审计。
4. **恶意输入最坏结果**：层级成环让路由死循环；悬空映射让需求映射到不存在的能力；`exact` 与包含
   关系共存让映射语义矛盾。缓解：校验全部在模型层 fail-closed，非法声明被拒绝写入。
5. **失败是否泄露信息**：校验错误只报告字段与规则，不含企业数据内容。

## 范围外

- 术语层存储（SLICE-218）、数据领域维（SLICE-219）、能力映射到 `tool_grants`/A2A（SLICE-220）、
  确定性路由（SLICE-221）。
- `exact` 映射的传递闭包推理（第二阶段）。

## 证据

- `docs/evidence/SLICE-217-semantics-data-model.txt`
