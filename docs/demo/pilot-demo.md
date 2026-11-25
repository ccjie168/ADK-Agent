# 五分钟试点演示（市场视图与工件状态）

这条演示脚本对应 SLICE-069。目标是在五分钟内让观众看到：已发布版本带工件摘要和验签徽标、能在详情区查看工件、能从市场切到聊天、能处理审批、能看运行与 trace，最后用 `verify-audit` 验证审计链。

## 准备

- 在仓库根目录使用 `.venv`，确认已安装发布依赖：`pip install -e '.[publish]'`。
- 打开两个终端。终端 A 跑审计服务，终端 B 跑控制台。
- 如果模型密钥没配置，聊天步骤会失败，但市场、审批、运行记录和审计链仍可演示。

## 0:00 播种演示数据

终端 B：

```bash
./.venv/Scripts/python.exe scripts/demo_seed.py --root demo --tenant acme
```

输出包含可信公钥路径和控制台启动命令。脚本做了这些事：

- 生成 Ed25519 密钥，写入 `demo/key.pem` 和 `demo/keys.json`（`demo-publisher`）。
- 打包、签名并发布 `acme/bot_a@1.0.0` 和 `acme/bot_b@1.0.0`，工件字节在 `demo/store`。
- 为 `bot_a` 写一份评测报告。
- 在 `demo/approvals` 写入一个待审批请求 `demo-approval-1`。

重复执行会复用已有密钥；换一套数据请换 `--root`。

## 0:30 启动审计服务

终端 A：

```bash
export ADK_MCP_AUTH_TOKEN=demo-token
./.venv/Scripts/python.exe -m adk_agent serve-audit --out demo/audit-chain.jsonl --host 127.0.0.1 --port 8010
```

审计服务把每条事件追加到带哈希链的 JSONL，供最后的 `verify-audit` 使用。

## 1:00 启动控制台

终端 B：

```bash
export ADK_ARTIFACT_KEYS="$(cat demo/keys.json)"
export ADK_BUILDER_KEYS="$(cat demo/keys.json)"
export ADK_MCP_AUTH_TOKEN=demo-token
./.venv/Scripts/python.exe -m adk_agent console \
  --registry demo/registry \
  --artifact-dir demo/store \
  --builder-keys demo/keys.json \
  --approval-dir demo/approvals \
  --audit-url http://127.0.0.1:8010 \
  --audit-token-env ADK_MCP_AUTH_TOKEN \
  --agent-ref acme/bot_a@1.0.0 \
  --agent-ref acme/bot_b@1.0.0
```

浏览器打开 `http://127.0.0.1:8000`，在 Bearer token 框输入 `demo-token`，点 Connect。

## 1:30 浏览市场

1. 切到 Registry 页签。租户下拉自动选中 `acme`，表格列出两个版本。
2. 每一行新增 artifact 列，显示状态徽标和摘要前 12 个十六进制字符，例如 `verified 3f2a9c01b4e7`。
3. 点 `bot_a` 行。详情区显示 manifest、评测报告和工件 JSON（`digest`、`size`、`key_id`、`status`）。
4. 点 `bot_b` 行。详情区切到另一个版本的工件。

## 2:00 徽标含义

| 徽标 | 含义 |
| --- | --- |
| `verified`（绿色） | 控制台配置了可信公钥，签名验签通过。 |
| `untrusted`（红色） | 验签失败：公钥不匹配或签名被篡改。 |
| `unknown`（灰色） | 控制台没有配置 `--artifact-keys` 或 `ADK_ARTIFACT_KEYS`，不猜测结论。 |
| `unsigned`（灰色） | 工件没有签名或没有 `key_id`。 |
| `-` | 该版本没有工件。 |

演示对比：先按上面的命令启动，全部显示 `verified`。去掉 `ADK_ARTIFACT_KEYS` 重启控制台，同一批工件变成 `unknown`；把 `keys.json` 换成另一把公钥，则变成 `untrusted`。

`ADK_BUILDER_KEYS`（或 `--builder-keys`）是另一条信任链：演示工件是 `in_process`，缺少它时载入会被拒绝。脚本用同一把演示密钥同时签发布与构建，生产上两者应由不同密钥承担。

## 2:30 从市场打开聊天

1. 在 Registry 页选中 `bot_b`，点 `Open chat`。
2. 页面切到 Chat 页签，agent 下拉自动选中 `bot_b`。
3. 若某个已发布版本没有用 `--agent-ref` 启动，点 `Open chat` 不会切页，详情区提示 `agent <id> is not loaded in this console`。

演示变体：只加 `--agent-ref acme/bot_a@1.0.0` 启动，选中 `bot_b` 再点 `Open chat`，即可看到上面的提示。

配好模型密钥后，在 Chat 页发一句话，右侧时间线显示运行进度，完成后出现 trace 编号。

## 3:15 审批

1. 切到 Approvals 页签，列表有一条 `demo-approval-1`，步骤 `step-1`，agent `bot_a`。
2. 点该行，详情区显示待审内容 `Send the customer a refund confirmation email.`。
3. 点 Approve 或 Deny。提示 `decided demo-approval-1`，列表清空。
4. 每次决定都会追加一条 `approval.decide` 审计事件。

## 3:45 运行与 trace

1. 切到 Runs 页签。有过聊天运行或审批决定后，列表按 `run_id` 聚合出现记录，显示 agent、状态、耗时、成本和事件数。
2. 点一行查看对应 trace：根事件是 `agent.run`，子事件是模型调用、工具调用等。
3. 审批决定产生的 trace 可能只有审批事件，没有运行根，页面显示 `trace not found`，这是预期行为。

## 4:15 验证审计链

终端 B：

```bash
./.venv/Scripts/python.exe -m adk_agent verify-audit demo/audit-chain.jsonl
```

通过时输出：

```text
ok 12 records
```

记录数取决于演示中产生的事件数。逐条重算哈希链，任何一段被改动都会报 `audit chain broken at record N` 并退出 1。设置了 `ADK_AUDIT_SIGNING_KEY` 或 `ADK_AUDIT_KEYRING` 时还会验签。

## 收尾

- 停掉两个终端里的服务进程。
- 演示状态都在 `demo/`：`registry`、`store`、`approvals`、`audit-chain.jsonl`、`key.pem`、`keys.json`。
- `key.pem` 是私钥，只留在本机，不提交、不外发。
