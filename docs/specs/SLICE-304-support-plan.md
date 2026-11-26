# SLICE-304 售后演示的计划审批链路

状态: active
依据: SLICE-303 的 mock 服务；用户确认「写工单用计划步骤审批」

## 意图

用一个可重复执行的验收脚本跑通：顺序计划 → 答疑步骤 → 建单步骤（L3，人工审批）→
调 mock ITSM 建单 → 调 mock 企业微信通知 → 审计链可校验。它是“售后值班 Agent”
全链路的第一条端到端证据，后续再换真实模型、A2A 与 WorkBuddy。

## 契约（先改）

`docs/demo/support-agent.md` 增加「计划审批链路（mock）」一节：

- 计划 `support-flow` 版本 `1.0.0`，策略 `sequential`，两步：
  `answer`（`support` Agent，无审批）与 `ticket`（`ticket_writer` Agent，
  `risk_level=L3`、理由“创建工单会通知客户”）。
- 脚本 `scripts/prove_support_demo.py`：自起 mock 服务、执行计划、批准审批、
  校验工单、微信消息与审计链，每步打印 `PASS`，失败退出 1。
- 审批结束后工单状态 `open`，微信消息含工单 id，审计里有
  `orchestration.approval`（ok）与 `orchestration.run`（ok）。

## 完成判据

- [ ] 脚本一次跑通全链路并输出 6 条 PASS -> `test_prove_support_demo_runs`
- [ ] 审批被拒时计划不建单、退出 2 -> `test_prove_support_demo_denied_path`
- [ ] 审计链可校验且含审批事件 -> `test_prove_support_demo_audits_approval`
- [ ] `--full` 门禁通过

## 反例

master 上脚本不存在；用例失败（找不到脚本 / 退出码非 0）。

## 5 问威胁建模

1. **数据**：演示工单与附件只在 mock 进程内存；脚本临时目录保存审计。
2. **调用方**：脚本本地运行，mock 用固定演示 token。
3. **信任边界**：只连 `127.0.0.1`；不触碰真实 ITSM/微信/夸克。
4. **恶意输入**：脚本参数只有 `--deny` 与 `--timeout`，无自由文本入命令。
5. **失败是否泄露信息**：只打印步骤名与错误码，不打印 token。

## 范围外

- 真实 LLM（脚本用确定性 AgentCall；模型接线在后续切片）。
- A2A/WorkBuddy 入口、工具网关连接器（后续切片）。
- 真实 WorkBuddy/夸克/企业微信。

## 证据

- `docs/evidence/SLICE-304-support-plan.txt`
