# SLICE-308 售后演示的写操作走工具网关

状态: active
依据: `docs/demo/support-agent.md`「后续切片」第 1 条（工具经工具网关调用 mock 服务）

## 意图

现在 `ticket_writer` 直接 HTTP 调 mock。改为经工具网关：

1. 演示把 mock ITSM 与微信登记成连接器（临时目录），起 `serve-tool-gateway` 等价的进程内网关，
   计划里的建单与通知都用 `ToolGatewayClient.invoke`（工具 id `mock-itsm`、`mock-wecom`）。
2. 网关只暴露连接器工具，鉴权为回环 bearer token + `--trust-caller-policy`（演示专用）。
3. 直接 HTTP 路径保留为默认，网关路径由 `--tool-gateway` 显式开启。

## 契约（先改）

`docs/demo/support-agent.md` 新增「工具网关（试跑）」一节：

- `prove_support_demo.py --tool-gateway`：自起 mock 后，在回环空闲端口起网关，
  计划里的两个写操作都经 `/v1/invoke`。连接器凭据引用 `secret://mock/token`，
  由脚本把 `ADK_SECRET_MOCK_TOKEN` 设为演示 token。
- 连接器：`mock-itsm`（`/itsm/`，L2）、`mock-wecom`（`/wecom/`，L2）；网关只加载这两个。
  工单连接器在网关里是 L2，因为 L3 审批已在计划步骤完成；平台没有工具级审批令牌，
  L3 连接器会被网关以 `approval_required` 拒绝。
- 平台侧三个小修（由本切片暴露）：
  - 连接器调用原先从不发送 `json_body`，POST 永远是空请求体；现在按 UTF-8 JSON 发送。
  - `HttpxAdapter` 增加 `trust_env` 开关，演示用 `False`，避免本机代理截走回环请求。
  - `ToolGatewayClient.invoke` 增加可选 `idempotency_key`（连接器工具按需要求），
    演示里统一携带。
- 新增 `PASS tools went through the gateway`，网关审计写 `gateway-audit.jsonl`。

## 完成判据

- [ ] 开启 `--tool-gateway` 时建单与微信都经网关 -> `test_support_demo_tool_gateway_path`
- [ ] 网关拒绝未注册的工具（只注册 mock-itsm 时调 mock-wecom 返回 403）-> `test_tool_gateway_denies_unregistered_tool`
- [ ] 默认路径不变（不传开关时仍是直接 HTTP）-> `test_support_demo_default_path_unchanged`
- [ ] 文档与脚本参数一致 -> `test_support_doc_mentions_tool_gateway`
- [ ] 连接器 POST 真正发送 JSON 请求体 -> `test_json_body_is_sent`
- [ ] `--full` 门禁通过

## 反例

master 上 `prove_support_demo.py` 没有 `--tool-gateway`，`support_demo_flow` 没有网关路径，
用例失败。

## 5 问威胁建模

1. **数据**：工单正文与微信文案走网关；token 只在进程环境里。
2. **调用方**：网关只监听回环、带 bearer；`--trust-caller-policy` 只用于本地演示。
3. **信任边界**：连接器仍做方法/路径/主机校验；网关只加载演示登记的两个连接器；
   `trust_env=False` 让回环请求不经过本机代理。
4. **恶意输入**：路径与 JSON 由连接器守卫校验；额度与超时沿用网关默认。
5. **失败是否泄露信息**：工具被拒只打印工具 id 与错误码，不打印 token。

## 范围外

- 真实工具网关部署、租户授权库与审批型工具（审批仍在计划步骤层）。
- 控制台连接器列表新增 `mock-wecom`（本切片只在演示目录登记）。

## 证据

- `docs/evidence/SLICE-308-support-gateway.txt`
