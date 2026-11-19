# ADR-0033 模型别名与路由

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

`build_model` 按字符串前缀解析 provider（`models/__init__.py:45`），`ModelPolicy` 只有
`provider_allowlist`（`core/manifest.py:22`），没有 alias、路由、降级、预算执行。FR-010 为 RED，
MVP 验收要求「至少两个批准模型端点，验证路由与降级」。代码结构必须收敛到
Model Policy → Model Alias → Gateway → Endpoint，不能让 `if provider == ...` 散落在业务代码。

## 决定

1. **manifest 增加 `model_alias`**，业务代码引用 alias，不硬编码供应商模型名。
2. **路由策略**：alias → 有序候选列表（primary + fallback），每个候选带 provider/model +
   数据分类准入。数据分类映射：受限数据只进批准端点（与 ADR-0021/D-21 联动）。
3. **降级**：主候选故障（503/超时）时路由到下一候选；权限与审计不因切换改变；审计记录
   alias + 实际模型 + 降级次数。
4. **预算**：每租户与每场景预算；超限降级或停止（MVP 先停止）。
5. **代码结构**：`build_model` 的前缀解析降级为「适配器选择」，不是「策略」；策略在网关路由器
   里。`provider_allowlist` 保留为路由器之下的硬门。

## 备选与否决

- **业务代码硬编码供应商模型名**：破坏模型可替换；否决。
- **全量多路智能路由（质量/成本加权）**：MVP 过度；先 alias + 主备 + 预算。
- **只做降级不做别名**：降级表仍散落供应商名，无法统一治理；否决。

## 后果

- `AgentManifest`、`ModelPolicy` 与网关 schema 变更；新增路由器组件。
- `model_allowlist`、`budget_usd` 目前声明未执行（`models/gateway.py` 只读 `provider_allowlist`），
  随本 ADR 落地执行。
- 成本/令牌/追踪已有（`models/gateway.py` 的 audit 与 `observability`），扩展到 alias 与降级事件。

## 切片（待确认后分配）

1. alias + 路由策略 schema（manifest/契约）。
2. 路由器 + fallback 执行。
3. 预算执行（`budget_usd`/每租户）。
4. 审计字段扩展（alias、实际模型、降级）。
