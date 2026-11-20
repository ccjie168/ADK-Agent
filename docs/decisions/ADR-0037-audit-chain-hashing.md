# ADR-0037 审计链哈希以存储内容为准

状态: Accepted   日期: 2026-11-21   签字: Jie CAO（会话确认）

## 背景

审计链的每条记录存 `prev_hash`、`hash` 与可选的 HMAC 签名。当前 `record_hash(event, prev_hash)`
用**当前代码里的模型**重新序列化事件再哈希：

```python
canonical = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
sha256(f"{prev_hash}\n{canonical}")
```

写入时与校验时都走这一条路径，只要模型不变就没问题。但每次给 `AuditEvent` 加字段，`model_dump`
的输出就变了，历史记录重算出来的哈希与存下来的不一致：

- SLICE-188 增加 `model_alias` 与 `fallback_count`，该切片之前写出的链在当前代码下全部验签失败。
- SLICE-198 增加 `rag_top_k` 等字段时再次触发，当时用 `exclude_if` 让未使用的字段不进入载荷才避免
  了新的断代。

`exclude_if` 只是让这一次不出事，治不了根：任何一次忘记写排除的新字段都会再断一次，而且已经断掉的
历史记录无法通过补排除恢复。`AuditPipeline` 启动与 `verify-audit` 都依赖这条校验，运维手册要求每日
验签，失败会被当成篡改处理。

## 决定

1. **哈希存下来的内容，而不是用当前代码解释存储内容。** 计算口径改为：取落盘的事件 JSON 对象，
   做规范排序（`sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False`），与 `prev_hash`
   拼接后 `sha256`。不再调用 `AuditEvent.model_dump`。
2. **写入时只序列化一次。** 写入路径先得到事件 JSON 文本，用同一份文本的解析对象算哈希，再把这份
   文本原样落盘（文件模式）或作为同一个参数写入（Postgres）。写入与校验共用 `canonical_event_json`
   一个函数，杜绝两边口径漂移。
3. **校验时从存储里取事件对象。** 文件模式取每条记录的 `event` 字段；Postgres 模式取 `event::text`
   的 JSON。两者都经过同一规范函数后比哈希。签名仍然只覆盖记录哈希，不变。
4. **不加 `hash_version` 字段，不重写历史。** 统一口径后，历史记录只要存储内容保留了当时的事件字段，
   就能按原样验签，包括 SLICE-188 之前的链。已经不一致的记录不做重签或迁移。
5. **新字段可以正常带默认值序列化。** `rag_*` 字段的 `exclude_if` 保留（少写冗余），但新字段不再
   必须写排除才能保证链稳定；这一点写进 `docs/contracts/audit_event.schema.json` 的说明与
   审计实现对开发者可见的注释。
6. **Postgres 用 `event::text` 的规范形式，不新增列。** `jsonb` 会规范化键顺序与数字表示，因此校验
   不能比对原始文本，只能比对规范形式。已在真实 Postgres 15 上实测：`0.0`、`1e-7`、`12345.6789`、
   `0.1+0.2`、`2^40` 整数与微秒时间戳经「写入文本 → `jsonb` → `event::text` → 规范函数」后与写入时
   的规范形式完全一致。因此不新增 `event_json` 列，也没有迁移；实现时用 `TEST_POSTGRES_URL` 的 live
   用例把这一点锁住。若将来出现某类值不保真，再单独评估加列（迁移需另行确认）。

## 备选与否决

- **加 `hash_version` 并按版本保留旧序列化器。** 要在代码里长期保留历代 `model_dump` 行为，字段一多
  就不可维护，且无法自动修好已经断掉的历史。否决。
- **重签或重写历史记录。** 审计链的意义是不变，重写等于销毁证据，即使有密钥也不该做。否决。
- **冻结 `AuditEvent` 不再加字段。** 审计需求必然会增长，冻结等于把问题推给下一个 ADR。否决。
- **维持现状，每次加字段都写 `exclude_if` 并接受旧链验不过。** 不可接受：运维无法区分「正常升级
  导致的断链」与「真的被篡改」。

## 后果

- 历史链重新可验；以后加字段不需要再考虑哈希兼容。
- 校验路径多一次解析与规范化的开销，量级与现在相当（本来就要解析成模型）。
- `verify-audit` 对 SLICE-188 之前写出的文件与数据库记录会恢复通过；运维手册需要写明这一点，避免
  把「升级后突然全部通过」误解为规则放松。
- 文件模式与 Postgres 模式必须共用规范函数，测试要覆盖两种存储的往返一致性（Postgres 部分需要
  `TEST_POSTGRES_URL` 的 live 用例）。

## 确认记录（2026-11-21 会话确认）

1. 接受「只改校验口径、不重写历史」：不重签、不迁移历史记录。
2. Postgres 不加 `event_json` 列、不做迁移；实测 `jsonb` 往返在规范形式下保真，由 live 用例锁定。
3. `rag_*` 字段的 `exclude_if` 保留。

## 切片（2026-11-21 确认后分配）

1. 抽出 `canonical_event_json` 与 `record_hash` 新口径，文件模式的写入与校验改造，补「旧格式记录仍可
   验签」的回归用例。
2. Postgres 模式改造与 live 往返用例；按第 6 条决定是否要新列。
3. `verify-audit` 输出与运维手册说明，`docs/contracts/` 的审计说明更新。
