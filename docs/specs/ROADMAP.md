# ROADMAP 企业级 agent 平台

状态: active   依据: ADR-0002   日期: 2026-11-11

## 规则

- 里程碑是门，不是日期。日期可以作为目标，不作为通过条件。
- 每个切片引用它实现的 ADR-0002 条款号。
- 切片不能和 ADR 冲突。实现中发现方向要改，先改 ADR 或出新 ADR，再改代码。
- 每个切片先写会红的反例测试，再实现。
- 每个切片完成跑 `python scripts/check.py --fast`，然后合并。
- 每个里程碑出口跑 `python scripts/check.py --full`，结果写进 `docs/evidence/`。
- 后续里程碑的切片在进入该里程碑时细化。现在只细化 M0。

## 文档链

```
ADR-0002 -> docs/contracts/ -> docs/specs/SLICE-xxx.md -> code -> docs/evidence/ -> scripts/check.py
```

为什么看 ADR，接口看契约，这一刀看 spec，证据看 evidence，强制看门禁。

## 里程碑

| 里程碑 | 阶段 | 出口标准 | 状态 |
| --- | --- | --- | --- |
| M0 地基 | Phase 0 | 五个契约合并，import-linter 生效，manifest 可往返，P0 加固完成 | done |
| M1 单 agent 闭环 | Phase 1 | 注册、发布、模型网关、审计端到端跑通 | done |
| M2 工具与策略 | Phase 2 | 越权工具调用被拒并留痕，沙箱生效 | done |
| M3 编排 | Phase 3 | 多 agent 工作流可回放，审批门生效 | planned |
| M4 平台加固 | Phase 4 | 两租户隔离，配额生效，评测不过不能发布 | planned |
| M5 拆分 | Phase 5 | 网关与 worker 独立部署，故障隔离 | planned |

## M0 切片

| 切片 | 内容 | 依据 | 依赖 |
| --- | --- | --- | --- |
| SLICE-008 | 核心契约与领域类型 | ADR-0002 第 2、3 条 | 无 |
| SLICE-009 | 包骨架、端口与分层门禁 | ADR-0002 第 2 条 | 008 |
| SLICE-010 | 评审 P0 加固 | ADR-0002 第 5、6 条 | 无 |
| SLICE-011 | 模型与配置契约收敛 | ADR-0002 第 2、3、8 条 | 008, 009 |

M0 出口证据见 `docs/evidence/M0-milestone.txt`。

M0 出口标准：

1. `docs/contracts/` 的五个 schema 合并，模型与 schema 一致。
2. `core/` 只定义类型和端口，import-linter 在 `check.py` 中强制。
3. `AgentManifest` 可 JSON 往返，未知字段被拒绝，digest 稳定。
4. 评审 P0 加固完成，`--fast` 全绿。
5. `check.py --full` 结果写入 `docs/evidence/`。

## M1 切片

- SLICE-012 注册表与发布：文件注册表、不可变版本、digest 钉住、`validate` / `publish` CLI、id/version 路径安全。
- SLICE-013 模型网关：provider 白名单、token 与成本审计、vLLM 适配器。
- SLICE-014 运行时注入：principal、run_id、trace_id 贯通。
- SLICE-015 基础模板：模板生成器与校验。
- SLICE-016 审计闭环与控制台 v0：内存审计、`/api/audit`、页面审计面板。
- SLICE-017 模型网关接入：把网关接到 ADK 模型循环，agent run 产生 `model.call` 事件。
- SLICE-018 安全门强制 Phase A：pre-commit hook、CI 必需检查、bandit 覆盖 scripts、spec 威胁模型门禁。

M1 出口证据见 `docs/evidence/M1-milestone.txt`。MCP `serve_agent` 路径的网关接入移到 M2。

SLICE-018 Phase B 需要新 ADR 或工具决策，排在 M2：依赖锁、历史密钥扫描、镜像扫描、SBOM 校验、日志脱敏。

进入每个切片时再写详细 spec。

## M2 切片

- SLICE-019 工具网关与策略：函数注册、GrantPolicyEngine、tool.call 审计。
- SLICE-020 ADK 工具守卫接入：before/after tool callback，agent 工具调用经过网关。
- SLICE-021 密钥提供者与工具源：SecretProvider、OpenAPI 导入、MCP 代理。
- SLICE-022 工具沙箱：资源与网络限制。

SLICE-019、SLICE-020、SLICE-021、SLICE-022 已完成。M2 收口。

M2 出口证据见 `docs/evidence/M2-milestone.txt`。

进入每个切片时再写详细 spec。

## M3 候选切片

- `OrchestrationPlan` schema。
- 单 agent、路由、监督者、工作流、扇出扇入策略。
- 持久化执行、重试、超时、预算、取消。
- 人工审批与 trace 树。

## M4 候选切片

- 多租户与配额。
- RBAC 与策略管理界面。
- 评测门禁与灰度。
- A2A 消费方与提供方评估。

## M5 候选切片

- 模型网关独立部署。
- 工具网关独立部署。
- 运行时 worker 横向扩容。
- 审计管线独立部署。

## 完成定义

一个切片完成，需要同时满足：

- spec 状态为 gated 或 merged。
- 反例测试先红，实现后绿。
- `check.py --fast` 全绿。
- 涉及对外接口时，契约已先合并。

一个里程碑完成，需要同时满足：

- 该里程碑所有切片合并。
- 出口标准逐条有证据。
- `check.py --full` 全绿，输出写入 `docs/evidence/`。
