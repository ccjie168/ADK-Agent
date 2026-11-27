# SLICE-309 售后专家接入 Claude Desktop（MCP）

状态: active
依据: 用户确认「WorkBuddy 用不了，先用 Claude Desktop 当入口验证平台」

## 意图

把 SLICE-306 的售后专家以 MCP 暴露给本机 Claude Desktop / Claude Code：

1. 一条命令生成 Claude Desktop 的 `mcpServers` 配置片段（绝对路径、环境变量、审批目录）。
2. 文档写清安装位置、审批是同步阻塞、以及能验证到哪些平台能力。
3. 端到端用例：MCP 初始化、列工具、调用工具、审批后建单。

平台侧的 MCP 服务（`serve --agent`）已具备，本切片不新增服务端能力；链路用例在实现前
就可能通过，故它主要守卫「配置生成器 + 文档 + 参数名」不漂移。红在生成器与文档缺失。

## 契约（先改）

新增 `docs/demo/support-mcp.md`：

- `scripts/mcp_desktop_config.py [--workdir DIR] [--mock-url URL] [--wait-seconds N]`
  输出 `{"mcpServers": {"adk-support": {...}}}`：
  - `command` 为当前解释器，`args` 为 `-m adk_agent serve --agent <绝对路径>/scripts/support_a2a_agent.py`；
  - `env` 含 `SUPPORT_MOCK_URL`、`SUPPORT_APPROVALS_DIR`、`SUPPORT_AUDIT_FILE`、
    `SUPPORT_WAIT_SECONDS`、`SUPPORT_MOCK_TOKEN`（演示 token），不输出任何真实密钥。
- Claude Desktop 配置路径：Windows `%APPDATA%\Claude\claude_desktop_config.json`，
  macOS `~/Library/Application Support/Claude/claude_desktop_config.json`；Claude Code
  用 `claude mcp add --transport stdio` 或项目 `.mcp.json`（只写 `${VAR}`）。
- 工具名 `support_flow`，参数 `request`（字符串）。

## 完成判据

- [ ] MCP 列出 `support_flow` 且有 `request` 参数 -> `test_support_agent_lists_over_mcp`
- [ ] 调用后审批通过则回复含工单号 -> `test_support_agent_answer_over_mcp`
- [ ] 配置生成器输出可直接粘贴的片段 -> `test_desktop_config_generator`
- [ ] 文档与生成器参数一致 -> `test_support_mcp_doc_matches_config`
- [ ] `--full` 门禁通过

## 反例

master 上没有 `scripts/mcp_desktop_config.py` 与 `docs/demo/support-mcp.md`；
生成器与文档用例失败。MCP 调用用例在实现前也会通过（平台已有能力），spec 如实记录。

## 5 问威胁建模

1. **数据**：用户问题与工单正文进本机进程；审批目录与审计文件在本地。
2. **调用方**：stdio，仅本机；不监听端口，没有网络鉴权面。
3. **信任边界**：Claude Desktop 启动子进程；agent 文件由操作员本机放置。
4. **恶意输入**：问题文本进审批请求与工单；mock 端做长度校验。
5. **失败是否泄露信息**：只回文本；不打印 token。

## 范围外

- 远程 MCP（streamable HTTP）与多用户鉴权。
- 真实 ITSM / 企业微信接入。

## 证据

- `docs/evidence/SLICE-309-support-mcp.txt`
