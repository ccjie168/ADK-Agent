# 售后专家接入 Claude Desktop（MCP）

目标：让本机 Claude Desktop / Claude Code 通过 MCP 调用平台的售后专家，问题、审批、建单与
审计都落到平台里。WorkBuddy 企业版需要已认证的企业微信组织才能开通，个人账号用不了；
MCP 这条路不需要任何外部账号。

## 生成配置

```bash
cd c:/AI_System/ADK-Agent
./.venv/Scripts/python.exe scripts/mcp_desktop_config.py
```

输出一段可以直接粘贴的 JSON：

```json
{
  "mcpServers": {
    "adk-support": {
      "command": "<仓库 .venv 的 python>",
      "args": [
        "-m", "adk_agent", "serve",
        "--agent", "<仓库>/scripts/support_a2a_agent.py"
      ],
      "env": {
        "SUPPORT_MOCK_URL": "http://127.0.0.1:8055",
        "SUPPORT_MOCK_TOKEN": "demo-token",
        "SUPPORT_APPROVALS_DIR": "<用户目录>/.adk/state/approvals",
        "SUPPORT_AUDIT_FILE": "<用户目录>/.adk/state/support-audit.jsonl",
        "SUPPORT_WAIT_SECONDS": "120"
      }
    }
  }
}
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--workdir DIR` | `~/.adk/state` | 审批与审计放在这个目录下 |
| `--mock-url URL` | `http://127.0.0.1:8055` | mock 服务地址，只接受回环 |
| `--wait-seconds N` | `120` | 等待人工审批的秒数 |
| `--python PATH` | 当前解释器 | 写进 `command` 的解释器路径 |

## 装到哪里

- **Claude Desktop（Windows）**：`%APPDATA%\Claude\claude_desktop_config.json`
- **Claude Desktop（macOS）**：`~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Code（CLI 与 VS Code 插件共用）**：见下节。

粘贴后重启 Claude Desktop。对话里问「客户登录不了怎么办」，Claude 会调用
`support_flow` 工具。

## Claude Code / VS Code 插件

不需要 Claude Desktop。Claude Code 本身就是 MCP 客户端，VS Code 插件读同一套配置。
用户级注册（不写进仓库）：

写成一行，PowerShell 不认行尾反斜杠续行（照抄多行会把命令注册成 `\`）。

```bash
claude mcp add --scope user adk-support --env SUPPORT_MOCK_URL=http://127.0.0.1:8055 --env SUPPORT_APPROVALS_DIR=C:/Users/Jie/.adk/state/approvals --env SUPPORT_AUDIT_FILE=C:/Users/Jie/.adk/state/support-audit.jsonl --env SUPPORT_WAIT_SECONDS=120 -- C:/AI_System/ADK-Agent/.venv/Scripts/python.exe -m adk_agent serve --agent C:/AI_System/ADK-Agent/scripts/support_a2a_agent.py
```

注册后用 `claude mcp get adk-support` 确认 `Status: ✔ Connected`；`/mcp` 里该服务器
显示 ✓ 与工具数。

或者在项目根建 `.mcp.json`（会被提交，按项目规则只写 `${VAR}`）：

```json
{
  "mcpServers": {
    "adk-support": {
      "type": "stdio",
      "command": "C:/AI_System/ADK-Agent/.venv/Scripts/python.exe",
      "args": ["-m", "adk_agent", "serve", "--agent",
               "C:/AI_System/ADK-Agent/scripts/support_a2a_agent.py"],
      "env": {
        "SUPPORT_MOCK_URL": "${SUPPORT_MOCK_URL}",
        "SUPPORT_APPROVALS_DIR": "${SUPPORT_APPROVALS_DIR}",
        "SUPPORT_AUDIT_FILE": "${SUPPORT_AUDIT_FILE}",
        "SUPPORT_WAIT_SECONDS": "120"
      }
    }
  }
}
```

注册后重载 VS Code 窗口，用 `/mcp` 确认 `adk-support` 为 connected；工具名形如
`mcp__adk-support__support_flow`。Claude Code 与 VS Code 插件共用这套配置。

## 延迟审批（不阻塞）

默认调用会等到审批结束。设置 `SUPPORT_DEFER=1` 后，需要审批时工具立即返回
「已提交，等待审批，request_id=…」，计划停在检查点；服务进程里的恢复器看到决策后
继续执行，结果体现在工单与审计里，不再占用调用方的连接。

| 变量 | 默认 | 说明 |
|---|---|---|
| `SUPPORT_DEFER` | `0` | `1` 时启用延迟审批 |
| `SUPPORT_NOTIFY_WEBHOOK_URL` | 未设置 | 可选，提交与决定都推送 |
| `SUPPORT_NOTIFY_SECRET_ENV` | 未设置 | webhook 的 HMAC 密钥所在环境变量名 |

状态查询走控制台：「审批」页看决策，运行审计看步骤。A2A 的 `input-required` 任务状态
按 ADR-0049 决定 9 推迟，等出现真实 A2A 客户端再实现。

## 会发生什么

1. 工具参数是 `request`（字符串），就是你问的那句话。
2. 平台先答问；需要建单时，审批请求写进 `SUPPORT_APPROVALS_DIR`，控制台「审批」页可见。
3. 调用是**同步阻塞**的：Claude 侧会一直等，直到批准、拒绝或超时
   （`SUPPORT_WAIT_SECONDS`，最长约 `wait + 60` 秒）。批准后返回「已创建工单 t-1」，
   拒绝返回「工单创建被拒绝，未执行。」。
4. 审计写两份：平台 MCP 运行审计在 `serve --audit-file`（未在上面配置里开启），
   计划审计在 `SUPPORT_AUDIT_FILE`。

## 能验证到什么

- MCP 入口、工具清单与参数 schema；
- 计划执行与人工审批；
- 工具网关（把 `SUPPORT_MOCK_URL` 换成走网关的演示时）；
- 审计链。配额与限流在 stdio 下不适用。

## 限制

- 只在本机 stdio，没有远程多用户鉴权。
- 审批阻塞调用；真实 IM 前端需要中间的「已收到，等待审批」回复。
- 控制台审批页要看到请求，两边必须用同一个 `--approval-dir`。
