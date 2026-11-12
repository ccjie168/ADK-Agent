# SLICE-037 把审计客户端接进两个网关

状态: in_progress
依据: ADR-0006 第 1、4、6 条，ADR-0004 第 7 条

## 意图（要什么，不写怎么写）

- `serve-model-gateway` 和 `serve-tool-gateway` 可以把审计事件发给独立审计服务，不再只写本地 JSONL。
- 目标由 `--audit-url URL` 表达。`--audit-file PATH` 保留。两者互斥。
- 审计服务的 bearer token 只从环境变量读。`--audit-token-env` 指定变量名，默认 `ADK_AUDIT_AUTH_TOKEN`。沿用 `--auth-token-env` 的规则，命令行永远不直接收 token。
- 非回环 URL 且没有 token 时拒绝启动。这条和审计服务自己的启动规则一致。
- 只换装配，`AuditSink` 端口和两个网关都不改。
- 审计服务不可用时错误向上抛，不吞。网关 HTTP 面因此返回 502。依据 ADR-0006 后果第 2 条。

这一刀不做重试、缓冲、批量、轮转和签名。

## 完成判据（可执行）

- [ ] `--audit-url` 让模型网关拿到 `HttpAuditSink` -> `tests/test_audit_sink_wiring.py::test_model_gateway_wires_http_audit_sink`
- [ ] `--audit-url` 让工具网关拿到 `HttpAuditSink` -> `tests/test_audit_sink_wiring.py::test_tool_gateway_wires_http_audit_sink`
- [ ] `--audit-file` 仍得到 `JsonlAuditSink` -> `tests/test_audit_sink_wiring.py::test_gateway_keeps_jsonl_sink`
- [ ] 两个审计参数都不给时网关不审计 -> `tests/test_audit_sink_wiring.py::test_gateway_without_audit_has_no_sink`
- [ ] token 从指定环境变量注入 -> `tests/test_audit_sink_wiring.py::test_audit_url_reads_token_from_env`
- [ ] 非回环 URL 带 token 时可以启动 -> `tests/test_audit_sink_wiring.py::test_non_loopback_audit_url_with_token_is_allowed`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`--audit-file` 和 `--audit-url` 同时给 -> argparse 退出 2 -> `tests/test_audit_sink_wiring.py::test_audit_flags_are_mutually_exclusive`
- [ ] 反例 2：非回环 `--audit-url` 没有 token -> 退出 1，提示缺少的环境变量名 -> `tests/test_audit_sink_wiring.py::test_non_loopback_audit_url_without_token_is_refused`

## 契约

- 先改 `docs/contracts/cli.md`，写清两个网关的新参数、互斥规则和失败语义。
- 不改 `AuditEvent` 和 `AuditRecord` schema。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件，含 run_id、trace_id、principal、provider、tokens、cost、args_hash、result_hash。
2. **调用方**：两个网关进程的运维命令行，以及环境变量提供方。
3. **信任边界**：网关进程到审计服务的 HTTP，命令行到环境变量。
4. **恶意输入最坏结果**：把事件发给攻击者控制的 URL 会泄露审计元数据。URL 由运维显式给出，不是外部输入。缓解是把 token 限制在环境变量里，非回环地址强制带 token。审计服务返回非 202 或连不上时抛 `AuditSinkUnavailable`，不静默丢事件。
5. **失败是否泄露信息**：启动失败只打印缺少的环境变量名，不打印 token 值。

## 证据

- 反例红: 待补
- 实现后绿: 待补
