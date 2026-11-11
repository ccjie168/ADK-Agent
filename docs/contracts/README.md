# 契约

本目录是对外接口的机器可读契约。文件由 `scripts/export_contracts.py` 从 `src/adk_agent/core/` 的 Pydantic 模型生成，不手改。

## 规则

- 改接口先改模型，再重跑导出脚本，再改调用方。
- `tests/core/test_contracts.py::test_contracts_in_sync` 会拒绝模型与 schema 不一致。
- 每个 schema 文件对应 ADR-0002 列出的一个领域类型。
- 生产只认 `AgentRef` 的 digest，不认 latest。
- 契约文件随版本提交，是审计和兼容性检查的锚点。

## 文件

- `manifest.schema.json`：`AgentManifest`，agent 的注册单元。
- `agent_ref.schema.json`：`AgentRef`，运行的版本锚点。
- `principal.schema.json`：`Principal`，每次调用的主体。
- `invocation.schema.json`：`Invocation`，数据面的调用形状。
- `audit_event.schema.json`：`AuditEvent`，追加审计事件。

`PublishedAgent` 不是独立契约，它是注册表对 `AgentManifest` 加 digest、签名和发布时间的包装。
