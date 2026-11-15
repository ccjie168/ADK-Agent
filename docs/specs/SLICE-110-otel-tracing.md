# SLICE-110 OTel 导出与 trace 瀑布

状态: gated
依据: 调研记录 `docs/research/agent-framework-landscape.md`；ADR-0021 已接受。

## 意图（要什么，不写怎么写）

把运行过程导出成 OpenTelemetry span，让 Langfuse、Phoenix 或任意 OTLP 后端能看到一次运行的瀑布。审计链继续保留，可观测与合规证据分开。

- 为 `agent.run`、`model.call`、`tool.call`、`a2a.call` 产生 span，父 span 是本次运行的根。
- 属性包含租户、run_id、trace_id、agent 引用、GenAI 操作名与模型名、token 用量、状态与耗时。
- 默认不导出 prompt、completion、工具参数原文。需要时由显式开关打开，并按数据分级限制。
- OTLP endpoint 可配置，默认关闭。导出失败只记录一次警告，不打断运行。
- 控制台或外部后端按 trace_id 展示瀑布，审计事件保持独立。

## 新增文件

- `src/adk_agent/observability/otel.py`
- `tests/test_otel_spans.py`
- `docs/decisions/ADR-0021-opentelemetry-export.md`

## 修改文件

- `src/adk_agent/runtime` 与 `src/adk_agent/orchestration` 的运行入口
- 模型网关、工具网关与 A2A 消费方的调用点
- `docs/guides/operations.md`

## 完成判据（可执行）

- [x] 一次运行产生根 span 与子 span，父子关系与 trace_id 正确 -> `tests/test_otel_spans.py::test_span_hierarchy`
- [x] 租户、run_id、agent 引用与 token 用量出现在属性里 -> `::test_attributes_and_usage`
- [x] 默认不包含 prompt、completion 与工具参数原文 -> `::test_no_content_by_default`
- [x] 没有 endpoint 时不导出，运行照常完成 -> `::test_disabled_without_endpoint`
- [x] 导出失败只告警一次，运行不失败 -> `::test_exporter_failure_is_soft`
- [x] 审计事件的 trace_id 与 OTel trace_id 一致 -> `::test_trace_id_matches_audit`
- [x] 非法 endpoint 只禁用导出，不崩溃 -> `::test_invalid_endpoint_is_disabled`
- [x] 不同租户的 span 属性不串 -> `::test_tenants_do_not_mix`

## 反例（必须在实现前跑红）

- [x] 反例 1：子 span 没有父 span -> 期望层级断言失败
- [x] 反例 2：工具参数含 token 原文进入属性 -> 期望 `::test_no_content_by_default` 失败
- [x] 反例 3：OTLP endpoint 非法 -> 期望启动告警并禁用导出，而不是崩溃
- [x] 反例 4：跨租户运行共用 trace_id -> 期望属性里各自租户正确

## 契约（如涉及对外接口）

不新增平台 API。导出属性名按 OpenTelemetry GenAI 语义约定，内部记录在 ADR-0021。

## 5 问威胁建模（10 分钟）

1. **数据**：运行元数据、token 用量、工具名、租户与主体标识；默认不含 prompt 与输出。
2. **调用方**：运行时、模型网关、工具网关、A2A 消费方、OTLP 后端。
3. **信任边界**：平台到外部可观测后端；租户之间的属性隔离。
4. **恶意输入最坏结果**：敏感内容被导出（缓解：默认不导出原文，属性白名单）；导出端点被伪造（缓解：endpoint 只从配置读取，凭据走 Secret）；导出故障拖垮运行（缓解：软失败）；跨租户 trace 混淆（缓解：每次运行独立 trace_id 与租户属性）。
5. **失败是否泄露信息**：告警只包含 endpoint 主机与错误类型，不打印凭据或载荷。

## 范围外

- 自建完整 trace UI。优先接 Langfuse 或 Phoenix。
- 默认开启 prompt 与 completion 采集。
- 用 OTel 替换审计链。

## 证据

- 反例红、实现后绿与门禁结果: `docs/evidence/SLICE-110-otel-tracing.txt`
- 依赖决定: `docs/decisions/ADR-0021-opentelemetry-export.md`
