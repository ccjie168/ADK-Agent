# ADR-0031 按集成类型的授权模式

状态: Accepted   日期: 2026-11-19   签字: Jie CAO（会话确认）

## 背景

连接器鉴权只有 `auth_ref`（`core/connectors.py:48`），走服务凭据，没有用户委托（OBO）。但单一
授权模式不成立：RAG/SharePoint 读适合服务身份 + ACL 执行，SAP 写只靠服务账号会丢失最小权限和
非抵赖。需要按集成类型区分执行身份，同时统一授权决策点与审计模型。

## 决定

1. **按集成类型的授权模式表**（授权决策挑战 §5）：

   | 集成类型 | 模式 |
   | --- | --- |
   | RAG / SharePoint | Service Identity + ACL enforcement |
   | Analytics / DSS / CDP（只读） | Service Identity + 下游 ACL / 行级过滤 |
   | ServiceNow 建单 | Controlled Service Identity + 审计(user+agent)；关闭/重大变更 HITL |
   | SAP 读 | Service Identity + ACL |
   | SAP 写 | Controlled Service Identity + HITL + 审计(user+approver+agent)；OBO 后置 |
   | MES 写 | 双人审批 + Controlled Service Identity |

2. **统一授权决策点。** `principal × resource × action × risk_level × approval` 在单一策略位置
   评估；执行下游调用用的「身份模式」是每个连接器的细节，不改决策点。
3. **OBO / 委托身份后置 P2。** 当写操作量大或需无接触自动化时再引入，引入前需新 ADR。
4. **高风险写审计必须含 user + approver + agent + service identity**，保证非抵赖。

## 备选与否决

- **全部 OBO**：最忠实最小权限，但 MVP 就引入 SAP 委托/principal propagation 复杂度与依赖；后置。
- **全部服务账号 + 审计**：SAP/MES 写丢失最小权限与非抵赖；否决。
- **单一模式**：与「按集成类型」冲突；否决。

## 后果

- `ConnectorSpec` 增加 `delegation` 字段描述执行身份模式（service / controlled-service+approval /
  oBo-later）。
- MVP 不新增依赖（OBO 后置）。
- SAP/MES 写保持 L3，在 ADR-0029 风险分级与 HITL 落地前不开放。

## 切片（待确认后分配）

1. `ConnectorSpec.delegation` 字段 + 契约。
2. 授权决策点接线（与 ADR-0028/0029 联动）。
3. SAP/MES 写模式（受控服务身份 + HITL + 审计）。
4. OBO 后置说明文档。
