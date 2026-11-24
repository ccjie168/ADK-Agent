# SLICE-272 安全合规聚合接口（GET /api/security）

状态: gated
依据: ADR-0042（已接受，含「校验有界」修订）

## 意图

新增只读聚合接口 `GET /api/security`（能力 `ops.read`），返回审计、密钥、策略、扫描四块摘要；
`?verify=1` 时按需校验审计链（仅文件后端），带 10 秒超时与 60 秒结果缓存。
扫描结果来自 `console --security-report PATH`（schema 见 `docs/contracts/security_report.schema.json`）。

要点：

1. **绝不返回密钥材料**：审计签名只给 active/kids/legacy，凭据只给按 key id 的计数与 `needs_rewrap`。
2. 审计查询失败、凭据 store 失败、KEK 未配置时返回 `null`/空对象并记日志，不 500。
3. 非文件审计后端返回 `error: "backend_unsupported"`（诚实显示，不假装已验证）。
4. 契约 `docs/contracts/console.md` 已补 `GET /api/security` 一节；新增 schema 文件。

## 完成判据

- [x] 无 `ops.read` 返回 403 `forbidden` -> `test_security_requires_capability`
- [x] 返回 audit/policy/keys/scans 四块，未配置时为 null -> `test_security_summarises_audit_and_policy`
- [x] 凭据存在时响应不含 `wrapped_secret` 内容（`test_security_counts_credentials_by_key` 内断言）
- [x] `?verify=1` 对空文件链返回 verified=true -> `test_security_verifies_the_file_chain`
- [x] 响应正文不含任何密钥值，只含 id -> `test_security_never_leaks_key_material`
- [x] 扫描报告文件被读取 -> `test_security_reads_the_scan_report`
- [x] 凭据按 key id 计数与 needs_rewrap -> `test_security_counts_credentials_by_key`
- [x] 非法 keyring 形状返回 `invalid_keyring`，不 500 也不回显内容 -> `test_security_rejects_ill_shaped_keyring`
- [x] memory 后端的 `last_event_at` 取最新事件 -> `test_security_lists_the_newest_memory_event`
- [x] `--full` 门禁通过

## 反例

实现前运行 tests/test_console_security.py：5 failed（路由不存在 → 404；`security_report` 参数不存在）。

## 5 问威胁建模

1. **数据**：审计元数据、key id 与计数、策略版本、CI 扫描摘要；无密钥值、无事件内容。
2. **调用方**：`ops.read`（admin + operator）。
3. **信任边界**：服务端从受信配置读取；扫描文件由运维写入，只按 schema 字段展示。
4. **恶意输入**：`?verify` 只接受 `1`；扫描文件解析失败按 null；环境变量 keyring 非法时只报 `invalid_keyring`。
5. **失败是否泄露信息**：固定错误码；不返回链内容。

## 范围外

- 非文件后端的链校验（需把 DSN 传入 console，另行评估）。
- 轮换动作（`credentials rewrap` 仍走 CLI）。
- 前端面板（SLICE-273）与 CI 汇总脚本（SLICE-274）。

## 证据

- `docs/evidence/SLICE-272-security-api.txt`
