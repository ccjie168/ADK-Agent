# SLICE-306 售后演示的 A2A 入口（mock WorkBuddy 客户端）

状态: active
依据: `docs/demo/support-agent.md` 的接入顺序（先把 mock 链路接到 A2A，再换真实 WorkBuddy）

## 意图

把 SLICE-303/304/305 的售后演示接到平台真正的 A2A 入口，而不是只在脚本里跑计划：

1. 一个 ADK agent 文件 `scripts/support_a2a_agent.py`，把「答问 + 建单（L3 人工审批）」
   计划包成一个 `BaseAgent`，可用 `serve-a2a --agent` 直接服务。
2. 一个假 WorkBuddy 客户端 `scripts/prove_workbuddy_a2a.py`：起 mock 服务与 `serve-a2a`，
   用 A2A JSON-RPC `message/send` 提问，等人工（或脚本）批准后校验回复、工单、微信与审计。
3. 平台侧小修：`install_tool_guard` 读取工具回调时用 `getattr`，跳过没有声明这些
   回调的自定义 `BaseAgent`，其子代理照常接入。原先 `serve-a2a --agent` 载入任何
   自定义 `BaseAgent` 都会在 `install_declared_guards` 处 `AttributeError` 退出。

## 契约（先改）

`docs/demo/support-agent.md` 增加「A2A 入口（mock WorkBuddy）」一节：

- `scripts/support_a2a_agent.py` 读取环境变量：
  - `SUPPORT_MOCK_URL`（默认 `http://127.0.0.1:8055`，只接受回环地址）：mock 服务基址；
  - `SUPPORT_APPROVALS_DIR`（默认 `support-approvals`）：审批请求目录，可与控制台共用；
  - `SUPPORT_AUDIT_FILE`（默认 `support-audit.jsonl`）：计划审计链文件；
  - `SUPPORT_WAIT_SECONDS`（默认 120）：等待审批的秒数，超时请求带 `expires_at`。
  模块级变量 `agent` 是入口，`name` 为 `support_flow`。
- `scripts/prove_workbuddy_a2a.py` 参数：`--workdir DIR`、`--interactive`、
  `--wait-seconds N`（默认 300）、`--deny`、`--port N`。
  成功打印 `PASS` 行与 `ALL PASS` 退出 0；拒绝退出 2；`--interactive` 超时打印
  `TIMEOUT` 退出 3；A2A 未带 token 时打印 `PASS anonymous call rejected`。
- A2A 调用是同步语义：HTTP 请求会一直等到审批完成或超时。超时后计划抛
  `ApprovalExpired`，A2A 返回 JSON-RPC 错误；文档需注明真实 WorkBuddy 应设置客户端超时。

## 完成判据

- [ ] 计划经 A2A 跑通并建单 -> `test_support_a2a_agent_approves_and_creates_ticket`
- [ ] 拒绝时不建单也不发微信 -> `test_support_a2a_agent_denies_without_ticket`
- [ ] 无 bearer token 的 A2A 调用被拒 -> `test_support_a2a_requires_bearer_token`
- [ ] mock WorkBuddy 客户端脚本端到端跑通 -> `test_workbuddy_a2a_end_to_end`
- [ ] 文档与脚本参数一致 -> `test_support_a2a_doc_matches_cli`
- [ ] 无工具回调的自定义 `BaseAgent` 不再让守卫安装失败 -> `test_install_guard_skips_agents_without_tool_callbacks`
- [ ] `--full` 门禁通过

## 反例

master 上没有 A2A 入口：两个脚本都不存在，`serve-a2a --agent scripts/support_a2a_agent.py`
报找不到文件，用例失败。

## 5 问威胁建模

1. **数据**：计划输入是用户问题；审批请求含问题文本；审批目录与审计文件只在本地。
2. **调用方**：只监听 `127.0.0.1`，带 bearer token；控制台与脚本共用审批目录。
3. **信任边界**：mock 服务只在不带 TLS 的回环；agent 文件由操作员本机放置，
   不经注册表加载，不涉及构建签名。
4. **恶意输入**：`message/send` 文本进入审批请求与工单；mock 端做长度校验；
   token 只从环境变量读取，脚本不打印。
5. **失败是否泄露信息**：只打印端口、路径与工单 id；异常路径打印错误类型，不打印 token。

## 范围外

- 真实 WorkBuddy Enterprise OpenAPI（`ck_`/`pt_`）与 IM 通道。
- 跨进程的异步审批（当前 A2A 调用阻塞到审批结束）。
- 工具网关调用 mock 连接器。

## 证据

- `docs/evidence/SLICE-306-support-a2a.txt`
