# SLICE-179 连接器风险/身份模式接入决策点

状态: gated
依据: ADR-0031（Accepted 2026-11-19）决定 2 / slice 2：把连接器的 `risk_level` 与 `delegation` 传播到
工具暴露面，使授权决策点（与 ADR-0028/0029 联动的 L4 拒绝、L3 审批、幂等）能看到连接器元数据。

## 意图

1. `ToolSpec`（tools/registry.py）增加 `delegation: DelegationMode = "service"`。
2. `ToolEntry`（tools/catalog.py）增加 `delegation: DelegationMode = "service"`。
3. `build_connector_tools`（tools/connectors.py）把 `ConnectorSpec.risk_level`/`delegation` 传播到 `ToolSpec`。
4. `connector_tool_entries`（tools/catalog.py）把 `ConnectorSpec.risk_level`/`delegation` 传播到 `ToolEntry`。

## 契约（先改）

- 无对外 schema 变更（`ToolSpec`/`ToolEntry` 为内部类型）。

## 完成判据

- [ ] build_connector_tools 传播 risk_level 与 delegation -> `test_build_connector_tools_propagates_risk_and_delegation`
- [ ] connector_tool_entries 传播 risk_level 与 delegation -> `test_connector_tool_entries_propagates_risk_and_delegation`
- [ ] ToolSpec.delegation 缺省 service -> `test_tool_spec_delegation_defaults_service`
- [ ] ToolEntry.delegation 缺省 service -> `test_tool_entry_delegation_defaults_service`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `build_connector_tools`/`connector_tool_entries` 丢弃连接器的 `risk_level`/`delegation`

## 5 问威胁建模

1. **数据**：连接器风险分级与身份模式。
2. **调用方**：工具网关、控制台目录视图。
3. **信任边界**：连接器定义到工具暴露面。
4. **恶意输入最坏结果**：L4 连接器被降级为无风险工具而绕过拒绝（缓解：传播 risk_level，决策点 L4 拒绝生效）。
5. **失败是否泄露信息**：纯字段传播，无新错误面。

## 范围外

- SAP/MES 写模式（slice 3）。
- OBO 后置说明（slice 4）。

## 证据

- `docs/evidence/SLICE-179-connector-decision-wiring.txt`
