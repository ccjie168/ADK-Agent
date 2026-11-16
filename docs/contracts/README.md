# 契约

本目录是对外接口的机器可读契约。文件由 `scripts/export_contracts.py` 从 `src/adk_agent/core/` 和身份适配器的 Pydantic 模型生成，不手改。

## 规则

- 改接口先改模型，再重跑导出脚本，再改调用方。
- `tests/core/test_contracts.py::test_contracts_in_sync` 会拒绝模型与 schema 不一致。
- 每个 schema 文件对应 ADR-0002 列出的一个领域类型。
- 生产只认 `AgentRef` 的 digest，不认 latest。
- 契约文件随版本提交，是审计和兼容性检查的锚点。

## 文件

- `manifest.schema.json`：`AgentManifest`，agent 的注册单元。
- `agent_ref.schema.json`：`AgentRef`，运行的版本锚点；`artifact_digest` 是可选的工作工件锚点。
- `agent_artifact.schema.json`：`AgentArtifact`，ADR-0008 的工件元数据（摘要、大小、入口、签名）。
- `agent_lifecycle.schema.json`：`AgentLifecycle`，ADR-0010 的版本生命周期状态。
- `principal.schema.json`：`Principal`，每次调用的主体。
- `invocation.schema.json`：`Invocation`，数据面的调用形状。
- `audit_event.schema.json`：`AuditEvent`，追加审计事件。
- `framework_config.schema.json`：`FrameworkConfig`，当前配置接口。M1 由 `AgentManifest` 取代，过渡期保留。
- `cli.md`：`adk-agent validate`、`adk-agent publish`、`adk-agent new` 的命令契约。
- `console.md`：控制台 `/api/agents`、`/api/chat`、`/api/audit` 的 HTTP 契约。
- `registry_service.md`：`serve-registry` 控制面端点、错误码与 HTTP 客户端语义。
- `oidc_config.schema.json`：`OidcConfig`，OIDC 身份适配器的配置。它是唯一从 `identity` 适配器导出的契约。
- `quota_config.schema.json`：`QuotaConfig`，按租户配置配额策略。
- `approval_request.schema.json`：`ApprovalRequest`，待人工审批的计划步骤。
- `approval_decision.schema.json`：`ApprovalDecision`，审批人的决定。
- `credentials.md`：租户凭据引用，只存元数据，引用映射到环境变量。
- `connector_requests.md`：连接器自助申请与管理员审批。
- `tracing.md`：入站 trace 头和出站 `X-Trace-Id` 的传播规则。
- `metrics.md`：各服务的 `/metrics` 端点、指标名和聚合边界。

`PublishedAgent` 不是独立契约，它是注册表对 `AgentManifest` 加 digest、签名和发布时间的包装，可选携带 `AgentArtifact`。
