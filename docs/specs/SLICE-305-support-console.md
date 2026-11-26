# SLICE-305 售后演示接入控制台（交互审批与 mock 连接器）

状态: active
依据: 用户 2026-11-27 确认「mock 在 UI 上可见、审批可在页面点」

## 意图

让售后演示不只停在脚本里：

1. 验收脚本可把审批写到控制台读取的目录，用 `--interactive` 停在「审批」页等人工点击；
   审计可写到控制台的审计文件。
2. 一个登记脚本把 mock ITSM 与夸克附件登记成平台连接器（带 `secret://` 凭据），
   控制台「生态」「连接器」页可直接看到。

## 契约（先改）

`docs/demo/support-agent.md` 增加「在控制台里操作」一节：

- `prove_support_demo.py` 新增 `--approvals-dir DIR`、`--audit-file FILE`、
  `--interactive`、`--wait-seconds N`（默认 300）。交互模式发出审批后不自动批准，
  等到决策文件出现；超时打印 `TIMEOUT` 并退出 3。
- `scripts/support_demo_register.py --connectors-dir DIR --credentials-dir DIR
  [--tenant local]` 写入：
  - 凭据绑定 `mock-token-ref`（`secret://local/mock_token`，enabled）；
  - 连接器 `mock-itsm`（HTTP，`/itsm/`，auth_ref 同上，L3）；
  - 连接器 `mock-quark`（HTTP，`/quark/`，auth_ref 同上，L2）。
- 控制台以 `--connectors-dir`、`--credentials-dir`、`--approval-dir`、`--audit-file`
  指向这些目录后，三页分别可见连接器、待批请求与审计事件。

## 完成判据

- [ ] 交互模式等人批准后继续建单 -> `test_support_demo_interactive_waits_for_decision`
- [ ] 无人批准时超时退出 3 -> `test_support_demo_interactive_timeout`
- [ ] 登记脚本写出连接器与凭据绑定 -> `test_register_mock_connectors`
- [ ] 控制台接口列出这两个连接器 -> `test_console_lists_mock_connectors`
- [ ] 文档与两个脚本的参数一致 -> `test_support_console_doc_matches_cli`
- [ ] `--full` 门禁通过

## 反例

master 上脚本没有交互与登记能力，控制台存储里也没有 mock 连接器；用例失败。

## 5 问威胁建模

1. **数据**：只写演示连接器定义与启用凭据绑定，不含密钥值；审批请求含问题文本。
2. **调用方**：登记脚本本地运行；审批仍由控制台的人完成。
3. **信任边界**：连接器只指向回环 mock；`secret://` 值来自环境变量。
4. **恶意输入**：目录与租户走安全名校验；超时与未决请求有确定退出码。
5. **失败是否泄露信息**：只打印路径、连接器 id 与错误码，不打印 token。

## 范围外

- 真实 WorkBuddy/夸克/企业微信。
- 工具网关真正执行 mock 连接器（连接器可见与工具执行是两件事）。
- 浏览器自动化点击审批（用控制台 API/人工点击）。

## 证据

- `docs/evidence/SLICE-305-support-console.txt`
