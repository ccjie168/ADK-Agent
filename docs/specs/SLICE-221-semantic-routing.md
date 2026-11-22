# SLICE-221 确定性语义路由

状态: gated
依据: ADR-0038 MVP 第 5 项（需求 → 概念 → 能力 → agent 的确定性映射，落到 `PlanStrategy`）。

## 意图

1. 定义 `RoutedCapability`：一次命中，含 `capability_id`/`concept_id`/`tool_id` 与命中的标签
   `matched_label`，让「需求 → 概念 → 能力 → 工具」整条链可审计。
2. `route_request(text, scheme, bindings)` 做确定性映射：需求文本大小写不敏感地匹配术语表里概念的
   标签（`pref_labels`/`alt_labels`/`hidden_labels`），命中的概念经 `CapabilityBinding` 映射到工具。
   返回按概念顺序排列的 `RoutedCapability` 列表，无命中返回空列表。
3. 这是纯确定性的，不引入模型；「计划结构怎么选」（`routing`/`fan_out` 等）属第二阶段，不在本切片。

## 契约（先改）

- `docs/contracts/semantics.md` 编排层补 `RoutedCapability` 与 `route_request` 的语义（匹配方式、
  顺序、空命中）。

## 完成判据

- [x] 命中概念经能力映射到工具 -> `test_route_matches_concept_label`
- [x] 无命中返回空列表 -> `test_route_returns_empty_when_no_match`
- [x] 同义词标签也能命中 -> `test_route_matches_alt_label`
- [x] 命中报告命中标签 -> `test_route_reports_matched_label`
- [x] 全量门禁通过

## 反例

- 基线 `4daa518`：没有 `RoutedCapability` 与 `route_request`，四个用例 `ImportError`。
- 若只匹配 `pref_labels` 不匹配 `alt_labels`，`test_route_matches_alt_label` 失败。

## 5 问威胁建模

1. **数据**：需求文本、术语标签、能力绑定。
2. **调用方**：编排执行器、控制台 Ask AI（后续）。
3. **信任边界**：用户自然语言 → 命中的能力与工具。
4. **恶意输入最坏结果**：需求文本构造出大量标签命中，触发不该用的工具。缓解：只做确定性的标签
   匹配，命中结果可审计；工具真正执行前的授权仍由既有工具网关/审批把关，本切片只做映射不执行。
5. **失败是否泄露信息**：只返回命中的能力与标签，不泄露术语表全文。

## 范围外

- 「计划结构怎么选」的模型填空（第二阶段）。
- 词义/向量匹配（用真实 embedding 后评估）。
- 把命中结果落到完整 `OrchestrationPlan`（tool → agent 的映射尚未定义）。

## 证据

- `docs/evidence/SLICE-221-semantic-routing.txt`
