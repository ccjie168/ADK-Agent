# 触发定义契约

一条触发记录把定时或 webhook 调用固定到一个已发布版本。执行服务见 SLICE-125。记录不含任何明文令牌或脚本。

## `AgentTrigger`

```json
{
  "trigger_id": "nightly-summary",
  "tenant": "acme",
  "agent_id": "assistant",
  "version": "1.0.0",
  "digest": "sha256:<64 hex>",
  "kind": "schedule",
  "every_seconds": 3600,
  "webhook_token_hash": null,
  "input": "Summarize yesterday.",
  "enabled": true,
  "created_by": "cli",
  "created_at": "2026-11-16T08:00:00Z"
}
```

- `kind` 取 `schedule` 或 `webhook`。
- `schedule` 必须有 `every_seconds >= 60`，不得有 `webhook_token_hash`。
- `webhook` 必须有 64 hex 的 `webhook_token_hash`，不得有 `every_seconds`。
- `digest` 存储形状是 `sha256:<64 hex>`。注册时也接受裸 64 位小写 hex，统一归一化为带前缀形状；执行服务与注册表记录核对时剥去前缀。
- `input` 是固定文本，最长 8000 字符。不做模板展开。
- `trigger_id`：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`。

## 令牌处理

注册 webhook 触发时，CLI 从环境变量读取明文令牌，长度至少 16。写入存储的是 `sha256(token)` 的 hex。明文不写入记录、不回显到 stdout 或 stderr、不进入日志。

执行服务用同一个哈希做 bearer 校验。SLICE-125 的 webhook 端点只在哈希匹配时运行。

## 存储

- 键是 `(tenant, trigger_id)`。
- 文件布局：`<root>/<tenant>/<trigger_id>.json`。重复登记相同内容幂等，不同内容冲突。
- Postgres：`adk_triggers(tenant text, trigger_id text, definition jsonb NOT NULL, updated_at timestamptz NOT NULL, PRIMARY KEY (tenant, trigger_id))`。
- 停用把 `enabled` 改成 `false`，重复停用幂等。

## CLI

`adk-agent triggers list --tenant TENANT [--dir DIR | --db URL]`

`adk-agent triggers register --tenant TENANT --id ID --agent-id AGENT --version VERSION --digest DIGEST (--every-seconds N | --webhook-token-env VAR) [--input TEXT] [--dir DIR | --db URL]`

`adk-agent triggers disable --tenant TENANT --id ID [--dir DIR | --db URL]`

- 后端二选一：`--dir DIR`（文件）或 `--db URL`（Postgres）。都未显式给出时读 `TRIGGER_DATABASE_URL`。显式文件与数据库同时给出，或显式参数与环境变量冲突，退出 2。
- `--webhook-token-env` 给出环境变量名；变量缺失或值短于 16 字符退出 1，不写存储。
- 成功输出记录 JSON；webhook 记录只显示 `webhook_token_hash`。失败 stderr 输出原因并退出 1。
- CLI 直接写存储，不产生审计，与现有管理命令一致。
