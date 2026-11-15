# ADR-0021 OpenTelemetry 导出边界

状态: Accepted   日期: 2026-11-15   签字: Jie CAO（会话确认）

## 背景

审计链能证明发生过什么，适合合规与追责。它不适合调试：没有 span 层级，没有耗时分解，也不能直接接到 Langfuse、Phoenix 或任意 OTLP 后端。调研记录 `docs/research/agent-framework-landscape.md` 把 OTel 导出列为 P0。

当前约束：

- 运行时依赖已经按哈希锁进 `requirements/runtime.lock`，新增依赖必须同时进运行时与开发锁。
- 平台以 Google ADK 为底座，模型与工具调用分散在运行时、模型网关、工具网关和 A2A 消费方。
- 审计事件里已经有 `tenant`、`run_id`、`trace_id`、`agent_ref`、`action`、`status`、`cost_usd`，可直接映射成 span 属性。
- 生产环境对 prompt、completion 与工具参数原文有数据分级要求，不能默认导出。

## 决定

1. **新增可选 extra `otel`。** `opentelemetry-api` 与 `opentelemetry-sdk` 已由 `google-adk` 传递引入，两个锁里已有 `1.45.2`；extra 里显式声明它们，避免依赖传递路径。本 ADR 唯一新增的包是 `opentelemetry-exporter-otlp-proto-http`，运行时锁与开发锁都包含该 extra，库消费者可以不安。
2. **默认关闭。** 只有设置了 `OTEL_EXPORTER_OTLP_ENDPOINT` 或显式传入 endpoint 时才创建 provider 与 exporter。没有 endpoint 时不安装全局 provider，调用点是空操作。
3. **span 结构固定。**
   - `agent.run` 是根，子 span 为 `model.call`、`tool.call`、`a2a.call`、`orchestration.step`、`approval.wait`。
   - 属性白名单：`adk.tenant`、`adk.run_id`、`adk.trace_id`、`adk.agent.id`、`adk.agent.version`、`adk.principal.subject`、`adk.action`、`adk.status`、`adk.error_code`、`adk.cost_usd`、`adk.args_hash`、`adk.tool.id`、`adk.a2a.target`，以及 GenAI 的 `gen_ai.operation.name`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`、`gen_ai.usage.output_tokens`。
   - 默认不导出 prompt、completion、工具参数与结果原文。需要内容级追踪时另立开关与数据分级评审。
4. **trace_id 与审计对齐。** 审计的 `trace_id` 作为 OTel trace id。有效时用远端父上下文注入，保证两边一致；无效时生成新的 trace id，并同时写入 `adk.trace_id` 属性。
5. **软失败。** exporter 初始化失败或导出异常只记录一次告警，不打断运行。审计链仍是权威记录，OTel 只做可观测。
6. **配置走标准环境变量。** `OTEL_EXPORTER_OTLP_ENDPOINT`、`OTEL_EXPORTER_OTLP_HEADERS`、`OTEL_SERVICE_NAME`、`OTEL_TRACES_SAMPLER`。凭据只从环境或 Secret 注入，不写进代码与仓库。
7. **测试用内存 exporter。** 单测断言 span 名称、父子关系、属性与无原文泄漏，不依赖外部后端。

## 备选与否决

- **自研 JSON trace 格式**：需要自己做 UI 与关联，生态无法复用；否决。
- **直接用 Langfuse SDK**：绑定单一厂商，OTel 是更通用的边界；否决。
- **OpenInference 包装层**：多一层依赖与映射，当前收益不明显；暂缓。
- **默认采集 prompt 与 completion**：数据分级与泄露风险过高；否决。
- **没有 endpoint 也创建 provider**：无意义开销与全局状态；否决。

## 后果

- 运行时镜像新增 OTel 与 protobuf 相关依赖，镜像体积增加，需要重新编译两个锁并重跑 Trivy。
- 导出端点成为新的信任边界，必须用 HTTPS 与受控凭据。
- OTel 语义约定会演进，升级依赖时需要复核属性名。
- 审计链继续是唯一权威证据；OTel 可以丢、可以采样。

## 切片

- SLICE-110：OTel 导出、信号接入、内存 exporter 测试、运行手册。

## 确认记录

2026-11-15 会话确认三点：

1. 接受新增 `otel` extra 并进入运行时与开发锁。
2. 接受默认关闭、默认不导出原文、exporter 软失败。
3. 接受审计 trace_id 作为 OTel trace id，审计链继续作为权威记录。
