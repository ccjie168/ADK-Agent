# 语义层契约

依据：ADR-0038。语义层分术语、能力、数据本体、编排四层；本契约先定义术语层与能力层的类型与校验。

## 术语层

`Term` 是一个语言里的一个标签：

- `value`（非空）：标签文本。
- `language`（非空）：语言代码，如 `en`、`zh`。

`Concept` 是一个概念：

- `concept_id`：稳定标识，`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`。
- `pref_labels`：首选标签，**每语言最多一个**，不能为空。
- `alt_labels`：同义/缩写标签，可多个。
- `hidden_labels`：拼写变体/口语叫法，用于检索不用于展示。
- `notation`（可选）：代码。
- `definition`（可选）：定义。
- `broader`：父概念 `concept_id` 列表，不能包含自身。
- `related`：相关概念 `concept_id` 列表，不能包含自身。

`ConceptMapping` 是两个概念间的一条映射：

- `source_id`、`target_id`：两端概念的 `concept_id`。
- `kind`：`exact` / `close` / `broad` / `narrow` / `related`。

`ConceptScheme` 是一个概念体系，承载集合级约束：

- `scheme_id`：体系标识。
- `concepts`：概念列表，`concept_id` 在体系内唯一。
- `mappings`：映射列表。

集合级校验：

- **层级无环**：`broader` 关系构成的有向图不能成环。
- **映射两端存在**：`source_id` / `target_id` 必须指向体系内的概念。
- **`exact` 一致**：`exact` 映射不允许 `source_id == target_id`；同一对两端之间，`exact` 不得与
  `broad` / `narrow` 同时存在（`exact` 是相等，`broad`/`narrow` 是严格包含，语义矛盾）。

## 能力层

`CapabilityId` 是 dot-namespaced 的能力标识，如 `order.lookup`：

- 形状 `^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$`：小写字母开头，段内小写字母、数字与下划线，段间点分隔。
- 它是术语与工具之间的锚点；与 A2A `skills`、MCP `tools/list` 的关联由 SLICE-220 定义。

`CapabilityBinding` 把一个能力 id 显式绑定到概念与工具：

- `capability_id`：dot-namespaced 能力 id。
- `concept_id`：关联的术语层概念。
- `tool_id`：关联的具体工具，对应 `tool_grants` 的 `tool_id` 或 A2A skill id。

`validate_capability_bindings(bindings, concept_ids, tool_ids)` 做集合级校验：能力 id 唯一、概念引用
存在、工具引用存在；任一悬空抛 `ValueError`。

## 数据本体层

`DataDomain` 是一条数据的领域标注，两维正交：

- `concept_id`（非空）：所属领域，引用术语层的概念 `concept_id`。租户可扩展，不限制在平台枚举。
- `sensitivity`：敏感度，`DataClass` 四值之一，缺省 `internal`。平台固定，租户不能自定义敏感度语义。

同一领域可配不同敏感度，同一敏感度可配不同领域，两者独立。

## 编排层（确定性路由）

`RoutedCapability` 是一次命中，含 `capability_id`/`concept_id`/`tool_id` 与命中的 `matched_label`，
让「需求 → 概念 → 能力 → 工具」整条链可审计。

`route_request(text, scheme, bindings)` 做确定性映射：需求文本大小写不敏感地匹配概念标签
（`pref_labels`/`alt_labels`/`hidden_labels`），命中的概念经 `CapabilityBinding` 映射到工具，返回按
概念顺序排列的 `RoutedCapability` 列表，无命中返回空列表。只做映射，不执行工具。

## 存储

`ConceptSchemeStore` 端口存整个 `ConceptScheme`，键是 `(tenant, scheme_id)`；`tenant` 是存储键，
不在 `ConceptScheme` 模型里：

- `put(tenant, scheme) -> ConceptScheme`：upsert，同键覆盖，术语表是声明式可更新的。
- `get(tenant, scheme_id) -> ConceptScheme | None`：缺失返回 `None`。
- `list(tenant) -> list[ConceptScheme]`：列出该租户全部术语表。

两个实现：文件后端（`<root>/<tenant>/<scheme_id>.json`，`safe_join` 原子写）与 Postgres 后端
（`adk_terminology` 表，jsonb，`ON CONFLICT DO UPDATE`）。租户隔离靠应用层 `WHERE tenant` 过滤，
MVP 不引入 RLS。存储不可用（坏 DSN、驱动缺失）统一抛 `ConceptSchemeStoreUnavailable`。

## 分层边界

- `adk_agent.semantics` 依赖 `adk_agent.core`；`core` 不得反向依赖 `semantics`（`.importlinter` 的
  `core-isolation` 已把 `adk_agent.semantics` 列入 forbidden）。
