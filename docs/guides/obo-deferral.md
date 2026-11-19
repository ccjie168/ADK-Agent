# OBO / 委托身份后置说明

依据：ADR-0031（按集成类型的授权模式）决定 3。

## 当前状态

连接器按 `delegation` 字段描述执行身份模式（`service` / `controlled-service` / `obo-later`）：

- 读集成（RAG/SharePoint、Analytics、SAP 读）用 **Service Identity + ACL**，`delegation="service"`。
- SAP/MES 写用 **Controlled Service Identity + HITL + 审计**，`delegation="controlled-service"`，
  由 `risk_level in ("L3","L4")` 强制审批（`ToolSpec.needs_approval`）。

OBO / 委托身份（on-behalf-of）**当前未实现**，`delegation="obo-later"` 是预留占位。

## 为什么后置

OBO 最忠实于最小权限，但会在 MVP 阶段引入 SAP 委托 / principal propagation 的复杂度与依赖。
当前「受控服务身份 + HITL + 审计（user + approver + agent）」已覆盖 SAP/MES 写的最小权限与非抵赖，
先落地再演进。

## 引入 OBO 的条件（P2）

满足任一条件时再引入，引入前必须新立 ADR：

1. 写操作量大到 HITL 成为吞吐瓶颈。
2. 需要无接触自动化（无人值守的写操作）。

## 引入前必须新立 ADR

引入 OBO 会新增身份传播链路、委托凭据生命周期与新的安全风险接受，必须单独 ADR 评审后才能实现。
在此之前，`delegation="obo-later"` 不进入执行路径。
