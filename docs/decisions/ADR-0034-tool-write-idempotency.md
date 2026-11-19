# ADR-0034 写工具幂等：网关级 idempotency_key 去重

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

工具网关输出序列化失败时，工具可能已实际执行成功，但客户端收到 502。调用方重试会导致重复
过账、重复建单（例如 SAP 已建 PO 12345，重试再建 PO 12346）。触发执行已有 idempotency_key
模式（`registry/trigger_runs.py`），但工具调用没有。SAP/MES 写是 L3，重复执行是真实业务风险，
须在 SAP/MES 写场景前定为 P0。

## 决定

1. **`ToolSpec`/`ToolEntry` 增加 `write: bool` 与 `idempotency_required: bool`。** 写工具
   （`write=true`）默认 `idempotency_required=true`。
2. **工具调用增加 `idempotency_key`。** 写工具缺 `idempotency_key` 直接拒绝（400），审计记
   `idempotency_missing`。
3. **网关维护 `idempotency_key → execution record → result` 映射。** 重复调用返回上次结果，
   不再执行。记录带 TTL 与 `(tenant, tool_id, idempotency_key)` 唯一约束，复用触发执行的
   文件 + Postgres 双实现模式（`registry/trigger_runs.py` / `trigger_runs_postgres.py`）。
4. **与风险分级联动（ADR-0029）。** L3/L4 写强制幂等；L2 写建议；L1 只读不需要。
5. **序列化失败语义。** 工具已执行但结果无法序列化时，记录按「执行成功但结果未知」处理，
   重试返回该状态而非重复执行；L3 情况升级人工确认。

## 备选与否决

- **只在文档里提醒调用方「重试前考虑幂等」**：不构成控制，SAP/MES 写风险不可接受；否决。
- **把幂等交给每个工具实现**：工具作者各自实现，无法统一审计与去重；否决，网关集中。
- **无 TTL 永久保存执行记录**：存储无限增长；否决，带 TTL + 归档。

## 后果

- 工具目录、`ToolSpec`、`ToolRequest` 与契约字段扩展。
- 网关新增幂等存储（文件 + Postgres），复用现有触发幂等模式，不新增依赖。
- SAP/MES 写场景的前置条件；在风险分级与 HITL（ADR-0029）落地前不开放写。

## 切片（待确认后分配）

1. `write`/`idempotency_required` 字段 + 契约（先红后绿）。
2. 网关幂等存储（文件 + Postgres）+ 缺 key 拒绝。
3. 重复 key 返回旧结果 + 序列化失败语义 + 测试。
4. 与 ADR-0029 风险分级联动（L3/L4 强制）。
