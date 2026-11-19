# M6：Enterprise Trust Chain

状态：草稿，待 Owner 确认。不修改 `docs/PROGRESS.md`、`docs/specs/ROADMAP.md` 与既有 ADR。
依据：`docs/review/` 反馈（2026-11-19）与 6 份 Proposed ADR（0028–0034）。

## 核心原则

**生产角色与策略权威 MUST NOT 来自用户可控的运行参数。**
`--role admin`、请求体 `policy`/`grants` 只能用于 DEV / 本地 / 集成测试，进入 UAT / PROD 必须
disable 或改由服务端权威解析。Identity → Policy → Agent → Model → Tool → System → Audit 的
信任链必须闭环，否则「独立部署网关」只是换了个位置，Trust Boundary 没有真正移动。

## 结论

**GO WITH CONDITIONS**（不是 Production Ready）。基础切片 SLICE-028 到 033 方向健康，但
SLICE-029 RBAC、030 Canary、032/033 网关的 Trust Boundary 尚未闭环，需先过下面 5 个 Gate。

## 5 个 Gate

| Gate | 现状 | 对应 ADR | 切片要点 | 验收（正例 / 反例） | 草拟测试用例名 |
| --- | --- | --- | --- | --- | --- |
| 1 OIDC → Principal → Tenant/Role | `--role` 默认 admin（`cli.py:1436`），角色是自由字符串 | ADR-0030 | 去 admin 默认、OIDC claim→角色、能力数据驱动 | OIDC 角色映射生效 / PROD 禁用 `--role admin` | `test_role_mapping` |
| 2 Tool Gateway 服务端授权 | 信任 caller `grants`（`tools/service.py`） | ADR-0028 | `ToolGrantStore` 服务端解析 + digest 缓存 | 伪造 grant 被拒 / 缺授权 403 | `test_tool_gateway_server_auth` |
| 3 Model Gateway 服务端策略 | 信任 caller `policy`（`models/service.py`） | ADR-0028 | `manifest.model_policy` 服务端解析 | 伪造 allowlist 被拒 / mismatch 403 | `test_model_gateway_server_policy` |
| 4 高风险 → HITL + 幂等 | 布尔 `requires_approval`；写工具无幂等 | ADR-0029 + ADR-0034 | `risk_level` L1–L4 + 写工具 `idempotency_key` | L3 缺审批不执行 / 重复 key 不重复执行 | `test_risk_hitl`、`test_write_idempotency` |
| 5 中心审计 / Trace 关联 | 哈希链 + HMAC + 跨服务 trace 已建成 | 验证项（无新 ADR） | 验证一次写操作 trace 可串联全链路 | user→agent→model→tool→system 一条 trace 可追溯 | `test_trace_correlation` |

## 与现有 SLICE-028..033 的关系

SLICE-028（tenant/quota）、029（RBAC）、030（eval/canary）、031（A2A）、032（model gateway）、
033（tool gateway）是已实现的 foundation。ADR-0028–0034 是在它们之上「把信任链闭环」的决策，
编号是 ADR 命名空间，不是新的 SLICE 编号。

## 顺序建议

1. Gate 1（ADR-0030）先行：服务端策略解析依赖可信 Principal，Principal 依赖 OIDC 角色映射。
2. Gate 2 + 3（ADR-0028）紧随：Policy Authority 落到服务端。
3. Gate 4（ADR-0029 + ADR-0034）：风险分级与写幂等，SAP/MES 写的前置。
4. Gate 5 是验证，随前三项一起用一条端到端 trace 证明。

## 明确后置（本轮不做）

- Planner / Specialist / Reviewer 作为独立 Agent（保留为能力需求，见 challenge 文档）。
- A2A 升级为核心依赖（保持 Optional）。
- 长期记忆、更多 Agent 模式。
- Teams 渠道、OBO / 委托身份、多模型智能路由。

## 进入真实 Enterprise Pilot 的判据

五项 Gate 全部通过后，架构从「设计得不错的 Agent Framework」进入「Enterprise Agent Runtime
Platform」。此前的实现均不算 Production Complete。
