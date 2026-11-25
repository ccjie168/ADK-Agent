# 审计链记录与哈希口径

依据：ADR-0037。链按租户独立，文件模式每条 JSONL 行与 Postgres 每行是一条记录。

## 记录结构

```json
{"event": {"...": "..."}, "prev_hash": "", "hash": "<hex>", "signature": "<hex>|null", "kid": "<id>|null"}
```

- `event` 是完整的审计事件对象（见 `audit_event.schema.json`）。
- `prev_hash` 是该租户上一条记录的 `hash`，首条为空串。
- `hash = sha256(prev_hash + "\n" + canonical(event))`。
- `signature` 是 HMAC-SHA256(记录 hash)，密钥来自 `ADK_AUDIT_KEYRING`/`ADK_AUDIT_SIGNING_KEY`；
  `kid` 标识签名密钥。

## 规范形式

`canonical(event)` 把事件对象按 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`
序列化。哈希的对象是**存储里的事件 JSON**，不是用当前代码重新序列化的模型：

- 文件模式取每行 `event` 字段的对象。
- Postgres 模式取 `event::text` 解析出的对象。

因此给事件加字段不会改变历史记录的哈希；新增字段按模型默认值序列化即可，不需要写排除。规范形式
只调整键顺序与空白，不丢弃字段，篡改任何字段都会断链。

## 字段演化

- 新增可选字段：直接加，历史记录不受影响。
- 删除或改名已有字段：历史记录的事件里仍有旧字段，哈希照旧覆盖它们，验证不受影响；读取方按
  当前模型解析时忽略未知字段即可（`extra` 配置需允许旧字段，或在解析前裁剪）。
- 改变某字段的值语义（例如时间时区）：属于事件内容变化，新记录用新值，旧记录按原样验证。

## Postgres 说明

`event` 列为 `jsonb`，写入时会规范化键顺序与数字表示。校验一律先取 `event::text`、按上面的规范形式
排序后比对，不比对原始文本。实测 `jsonb` 往返在规范形式下保真（含 `0.0`、`1e-7`、大浮点、大整数与
微秒时间戳），由 live 用例锁定。

## 兼容读取（SLICE-282）

查询端（`query_events`、`GET /v1/events`、控制台的审计/运行/trace 面板）先按 `AuditRecord` 解析每行，
失败再按裸 `AuditEvent` 解析：

- 链记录：`serve-audit --out`、`--audit-db` 与 `AuditPipeline` 的产物。
- 裸事件：`console --audit-file` 等走 `JsonlAuditSink` 的命令产物，只含事件字段，没有 `prev_hash`/`hash`/签名。

两种行都失败时保持原行为：当前文件的最后一行视为半写行跳过，其他位置抛错。

校验侧不变：`verify-audit` 只接受链记录，裸事件文件需要改用 `serve-audit --out` 重新采集才能验链。
读取端不做链校验，接受裸事件不会给写入者新增能力。
