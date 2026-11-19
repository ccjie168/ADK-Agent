# SLICE-178 连接器 delegation 字段

状态: gated
依据: ADR-0031（Accepted 2026-11-19）决定 1 / slice 1：`ConnectorSpec` 增加 `delegation` 字段描述
执行身份模式（service / controlled-service / obo-later）。本切片只加字段与契约，决策点接线后置。

## 意图

1. `ConnectorSpec`（core/connectors.py）增加 `delegation: Literal["service", "controlled-service", "obo-later"]`，缺省 `service`。
2. 导出 `DelegationMode` 字面量。
3. `docs/contracts/connector_requests.md` 补充字段说明。

## 契约（先改）

- `docs/contracts/connector_requests.md`：`ConnectorSpec` 示例与字段说明增加 `delegation`。

## 完成判据

- [ ] 接受 controlled-service -> `test_connector_accepts_delegation`
- [ ] 拒绝未知 delegation -> `test_connector_rejects_unknown_delegation`
- [ ] 缺省为 service -> `test_connector_delegation_defaults_service`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `ConnectorSpec` 无 `delegation` 字段（extra_forbidden）

## 5 问威胁建模

1. **数据**：连接器执行身份模式。
2. **调用方**：连接器登记、控制台/CLI、工具网关。
3. **信任边界**：连接器定义 schema 到执行。
4. **恶意输入最坏结果**：写连接器被误标为 service 而丢失 HITL（缓解：缺省 service 为只读，写模式在决策点按 risk_level 联动）。
5. **失败是否泄露信息**：纯字段校验，无新错误面。

## 范围外

- 授权决策点接线（ADR-0031 slice 2）。
- SAP/MES 写模式（slice 3）。
- OBO 后置说明（slice 4）。

## 证据

- `docs/evidence/SLICE-178-connector-delegation.txt`
