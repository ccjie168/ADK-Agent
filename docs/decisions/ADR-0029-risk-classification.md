# ADR-0029 风险分级模型：L1–L4 替代布尔审批

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

当前工具授权只用布尔 `requires_approval`（`core/policy.py:17` 的 `ToolGrant`、
`tools/catalog.py:30` 的 `ToolEntry`、`core/orchestration.py:71` 的 `PlanStep`）。它表达不了
目标规格 §12.1 的 L1–L4 风险分级：知识问答自动、建单可自动、SAP/MES 写入必须审批、L4 默认拒绝。
风险分级直接决定工具授权 → 审批要求 → 执行策略 → 审计，不是架构洁癖。

## 决定

1. **新增 `risk_level: Literal["L1","L2","L3","L4"]`**，落在 `ToolEntry`、`ToolGrant`、
   `PlanStep`（以及连接器暴露为工具时的派生字段）。
2. **分级到审批策略的映射**（目标 §12.1）：
   - L1：自动执行，记录与引用。
   - L2：自动或轻审批，政策检查。
   - L3：必须人工审批 + 影响预览 + 幂等 + 补偿。
   - L4：默认拒绝，仅安全/业务 Owner 特批。
3. **审批要求由风险等级推导，不再单独维护布尔。** 过渡期保留 `requires_approval` 作为兼容字段，
   语义为「L3 及以上」，新代码只写 `risk_level`。
4. **风险等级进审计事件**，审计记录每个工具/步骤动作的风险等级（`core/audit.py` 的
   `AuditEvent` 增加字段）。
5. **L4 拒绝在授权决策点执行**（ADR-0028 服务端），不在工具处理器里补丁式拦截。

## 备选与否决

- **保持布尔 + 加审批原因字符串**：无法表达「建单自动、关闭审批」的同一工具不同动作分级；否决。
- **L1–L4 只做文档约定，不改数据结构**：策略无法被程序执行与审计，违背 fail-safe；否决。

## 后果

- 工具目录、连接器、manifest、契约都要加 `risk_level`，是跨模块 schema 变更。
- `PlanExecutor` 的 `requires_approval` 步骤门改为按 `risk_level` 驱动（`orchestration/executor.py`）。
- 存量 `requires_approval=true` 映射为 L3；无审批的读写默认 L2/L3 需在迁移切片里定，不能静默
  放宽既有授权。
- L4 特批需要独立的特批流程与审计（后续切片，MVP 内先默认拒绝）。

## 切片（待确认后分配）

1. core 类型 + `risk_level` 字面量与 schema。
2. `ToolEntry`/`ToolGrant`/`PlanStep`/`ConnectorSpec` 增加字段 + 契约。
3. `PlanExecutor` 审批门改按风险等级驱动 + 审计字段。
4. 授权决策点 L4 拒绝 + 特批审计（可后置）。
