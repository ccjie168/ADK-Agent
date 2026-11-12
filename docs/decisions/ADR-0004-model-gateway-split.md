# ADR-0004 先拆模型网关

状态: Accepted   日期: 2026-11-12   批准: Jie CAO（会话确认）

## 背景

ADR-0002 第 9 条要求按接缝拆服务，模型网关和工具网关最先拆，因为它们是安全边界。M5 候选里有四个接缝，需要一个先后顺序和第一刀的形态。

现状：模型调用在进程内经过 `GatewayLlm` 和 `PolicyModelGateway`。没有独立的部署单元，也没有跨进程契约。

## 决定

1. 第一刀拆模型网关。它是所有模型出口的唯一通道，信任边界独立，扩缩容需求最先出现。
2. 进程内适配器保留为默认。拆出的服务是可选部署，不强制。
3. 跨进程契约进 `docs/contracts/`：`ModelGatewayRequest` = invocation + request + policy。响应复用 `ModelResponse`。
4. HTTP 服务是无状态的。会话、任务、账本不在网关进程里。
5. HTTP 服务必须鉴权。非回环地址没有 token 拒绝启动。`/healthz` 是唯一开放路径。
6. 失败隔离：网关不可用返回 502，调用方拿到 `ModelGatewayError`；策略拒绝映射为 403 `model_denied`。
7. 审计在网关进程内写 JSONL（`JsonlAuditSink`）。独立审计管线是后续切片。
8. 调用方通过 `HttpModelGateway` 走端口，不直接拼 HTTP。

## 后果

- 平台可以只部署一个网关进程，多个运行时共享。
- 服务信任持 token 的调用方送来的 policy。per-caller 策略权威需要身份映射，排在 OIDC 接入之后。
- JSONL 审计是单进程文件，不是最终形态。
- 工具网关拆分的形态沿用本 ADR：同样的契约、鉴权和失败隔离规则。
