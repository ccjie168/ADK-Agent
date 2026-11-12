# SLICE-032 模型网关独立部署（M5-1）

状态: gated
依据: ADR-0002 第 5、9 条，ADR-0004

## 意图（要什么，不写怎么写）

进入 M5 的第一刀。

- 模型网关成为可独立部署的 HTTP 服务。
- 跨进程契约进 `docs/contracts/`：invocation + request + policy。
- 服务无状态，鉴权，非回环无 token 拒绝启动。
- 策略拒绝映射 403，provider 失败映射 502，不泄露内部细节。
- 审计在网关进程写 JSONL。
- 调用方走 `HttpModelGateway`，注入客户端的构造方式便于测试。
- 进程内网关不变，服务是可选部署。
- 这一刀不拆工具网关，也不接 OIDC 身份映射。

## 新增文件

- `src/adk_agent/core/gateway.py`
- `src/adk_agent/models/service.py`
- `src/adk_agent/models/http_gateway.py`
- `src/adk_agent/audit/jsonl.py`
- `tests/models/test_model_service.py`
- `tests/models/test_http_gateway.py`
- `tests/audit/test_jsonl_sink.py`
- `docs/contracts/model_gateway_request.schema.json`
- `docs/evidence/SLICE-032-model-gateway-service.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`：导出 `ModelGatewayRequest`
- `src/adk_agent/core/model.py`：无改动，响应复用 `ModelResponse`
- `src/adk_agent/audit/__init__.py`：导出 `JsonlAuditSink`
- `src/adk_agent/models/__init__.py`：导出客户端与服务构造
- `src/adk_agent/cli.py`：`serve-model-gateway`
- `scripts/export_contracts.py`：导出新 schema
- `docs/contracts/cli.md`：新命令
- `docs/specs/ROADMAP.md`：M5 进度

## 完成判据（可执行）

- [x] 契约往返 -> `tests/models/test_model_service.py::test_request_contract_roundtrip`
- [x] 服务无 token 拒绝网络绑定 -> `::test_network_bind_requires_token`
- [x] `/healthz` 开放，`/v1/complete` 要 token -> `::test_healthz_open_and_rpc_protected`
- [x] 正常调用返回 ModelResponse -> `tests/models/test_http_gateway.py::test_client_roundtrip`
- [x] 策略拒绝映射 403 与 ModelDenied -> `::test_client_maps_denied`
- [x] token 错误抛 ModelGatewayError -> `::test_client_rejects_bad_token`
- [x] provider 异常映射 502 -> `::test_client_maps_provider_failure`
- [x] JSONL 审计一行一事件 -> `tests/audit/test_jsonl_sink.py::test_append_writes_one_json_per_event`
- [x] 审计事件可回读 -> `::test_events_roundtrip`
- [x] provider 构造校验 -> `tests/models/test_model_service.py::test_build_providers`
- [x] 契约 schema 同步 -> `tests/core/test_contracts.py::test_contracts_in_sync`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.models.http_gateway import HttpModelGateway` -> 当前 `ImportError`
- [x] 反例 2：`from adk_agent.core import ModelGatewayRequest` -> 当前 `ImportError`
- [x] 反例 3：非回环地址建服务无 token -> 期望 `ValueError`
- [x] 反例 4：无 token 调用 `/v1/complete` -> 期望 401
- [x] 反例 5：provider 抛错时服务泄露异常信息 -> 期望通用 502

## 契约

```python
class ModelGatewayRequest(BaseModel):
    invocation: Invocation
    request: ModelRequest
    policy: ModelPolicy
```

- `POST /v1/complete`，请求体是 `ModelGatewayRequest`，响应是 `ModelResponse`。
- 403 `{"error": "model_denied"}`，502 `{"error": "model_call_failed"}`。
- `GET /healthz` 返回 `{"status": "ok"}`，不需要 token。
- 其他路径都要 bearer token。
- `build_model_gateway_app(gateway, *, host, auth_token, allow_unauthenticated)` 先走 `resolve_http_auth`。
- `HttpModelGateway(base_url, *, auth_token, client=None, timeout=60.0)` 的 `complete` 走端口签名。
- `JsonlAuditSink(path)` 每个事件一行 JSON，追加写入，`fsync` 后返回。

## 5 问威胁建模（10 分钟）

1. **数据**：消息内容、provider、model、policy、token、成本与 token 数。
2. **调用方**：运行时 worker、控制台、后续编排服务。
3. **信任边界**：HTTP 网络、bearer token、provider SDK、审计文件。
4. **恶意输入最坏结果**：匿名调用消耗模型额度；伪造宽松 policy 越过 agent 允许列表；大 payload 打爆内存；服务错误回显 provider 密钥或内部 URL。用强制鉴权、回环例外、通用错误体、pydantic 严格校验处理。
5. **失败是否泄露信息**：403 和 502 只给固定错误码。审计写 action、target、hash，不写正文。

### 已知边界

- 服务信任调用方送来的 policy。per-caller 策略权威要等身份映射。
- JSONL 审计是单进程文件，没有轮转和集中投递。
- 没有请求大小上限和速率限制，沿用后端的承载能力。
- 没有重试和熔断，客户端只做超时和错误映射。
- `GatewayLlm` 还没切换成 HTTP 后端。这一刀提供端口和服务，切换是后续切片。

## 证据

- 反例红: `ImportError: cannot import name 'JsonlAuditSink'` 等，3 个测试模块收集失败
- 实现后绿: 服务、客户端、JSONL 测试 12 passed
- 真实服务: `/healthz` 200；带 token 调用返回文本与 token 数；错误 token 401 映射为 `ModelGatewayError`；越权 policy 映射为 `ModelDenied`
- 审计文件: 一条 ok、一条 denied，都是完整 AuditEvent JSON
- `check.py --fast` -> 311 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 311 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-032-model-gateway-service.txt`
