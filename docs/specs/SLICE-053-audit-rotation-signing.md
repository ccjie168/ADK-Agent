# SLICE-053 审计轮转与签名

状态: gated
依据: SLICE-035，SLICE-037，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

审计文件目前是一个只增的 JSONL，没有大小上限，也没有能证明记录没被替换的签名。这一刀加按记录数的轮转和逐记录 HMAC 签名。

- `AuditPipeline(path, *, max_records=None, signing_key=None)`。当前段写满 `max_records` 条后改名为 `<name>.000001`、`<name>.000002`，新记录继续写基础路径。哈希链跨段连续。
- 启动时按段顺序重放所有段，恢复每个租户的最后哈希和当前段计数。
- `load_records` 和 `verify_audit_file` 按段顺序处理所有段，记录的全局序号用于报错定位。
- 设置签名密钥时，每条记录的 `signature` 是 `HMAC-SHA256(key, record.hash)`。`AuditRecord` 新增可选 `signature`，格式 64 位小写十六进制。
- `verify_audit_file(path, signing_key=None)`。给了密钥时，每条记录都必须有匹配签名；缺失或不匹配抛 `AuditSignatureInvalid`。不给时只验链。
- CLI：`serve-audit` 新增 `--audit-max-records N`，从 `ADK_AUDIT_SIGNING_KEY` 读签名密钥；`verify-audit` 也从同一个环境变量读，存在时强制验签。

这一刀不做密钥轮换、多密钥 id、外部 KMS、远程归档。

## 新增文件

- `tests/audit/test_rotation.py`
- `tests/audit/test_signing.py`
- `tests/test_cli_audit_rotation.py`
- `docs/evidence/SLICE-053-audit-rotation-signing.txt`

## 修改文件

- `src/adk_agent/core/audit.py`：`signature`
- `src/adk_agent/audit/pipeline.py`：轮转、签名、跨段校验
- `src/adk_agent/audit/__init__.py`：导出 `AuditSignatureInvalid`、`record_signature`
- `src/adk_agent/cli.py`：`--audit-max-records`、环境变量签名
- `docs/contracts/audit_record.schema.json`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AuditRecord:
  event, prev_hash, hash, signature: str | None

AuditPipeline(path, *, max_records: int | None = None, signing_key: str | None = None)

段文件:
  <path>.000001, <path>.000002, ..., <path>   # 基础路径是当前段

signature = HMAC-SHA256(signing_key.encode(), record.hash.encode()).hexdigest()

verify_audit_file(path, signing_key=None) -> int
```

轮转规则：

- 写之前如果当前段计数 `>= max_records`，先把当前段改成下一个序号，计数归零，再写新记录。
- 基础路径不存在时直接从 0 计数。
- 序号取已有段的最大值加一，六位补零。

## 完成判据（可执行）

- [x] 写满后轮转 -> `tests/audit/test_rotation.py::test_rotates_segments`
- [x] 恰好写满不轮转 -> `tests/audit/test_rotation.py::test_rotates_only_when_full`
- [x] 哈希链跨段连续 -> `tests/audit/test_rotation.py::test_chain_continues_across_segments`
- [x] 重启后接着写已有段 -> `tests/audit/test_rotation.py::test_restart_reads_all_segments`
- [x] 默认不轮转 -> `tests/audit/test_rotation.py::test_no_rotation_by_default`
- [x] 校验跨段并定位篡改 -> `tests/audit/test_rotation.py::test_verify_spans_segments`
- [x] 签名记录能用同一密钥验证 -> `tests/audit/test_signing.py::test_signed_records_verify`
- [x] 错误密钥失败 -> `tests/audit/test_signing.py::test_wrong_key_fails`
- [x] 有密钥但记录没签名时失败 -> `tests/audit/test_signing.py::test_missing_signature_fails`
- [x] 签名被篡改时失败 -> `tests/audit/test_signing.py::test_signature_tamper_fails`
- [x] 没密钥时只验链 -> `tests/audit/test_signing.py::test_unsigned_verify_without_key`
- [x] CLI 用环境变量验签 -> `tests/audit/test_signing.py::test_verify_command_uses_env_key`
- [x] CLI 转发轮转参数和密钥 -> `tests/test_cli_audit_rotation.py::test_serve_audit_forwards_rotation_and_key`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.audit import AuditSignatureInvalid` -> 当前 `ImportError`
- [x] 反例 2：`AuditPipeline(path, max_records=2)` -> 当前 `TypeError`，不认识该参数
- [x] 反例 3：写 5 条后没有段文件 -> 当前只有基础文件
- [x] 反例 4：`AuditRecord(..., signature=...)` -> 契约模型已先加字段；当前管线不写签名
- [x] 反例 5：`serve-audit --audit-max-records 2` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/`。已改：

- `audit_record.schema.json` 加可选 `signature`。
- `cli.md` 的 `serve-audit` 和 `verify-audit` 两节。

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件、哈希链、签名、密钥、段文件。
2. **调用方**：网关、服务、运维、审计校验。
3. **信任边界**：应用进程到磁盘，运维到校验命令，环境变量到进程。
4. **恶意输入最坏结果**：删除或替换段文件；重放旧段；去掉签名绕过验签；密钥进仓库或日志。缓解是跨段连续哈希链、有密钥时强制每条签名、签名覆盖记录哈希、密钥只从环境变量读且不打印。没有密钥时只能发现断链，不能发现整段替换，这一点写进文档。
5. **失败是否泄露信息**：校验失败只报记录序号和租户，不输出事件内容。密钥不出现在错误信息里。

## 范围外

- 密钥轮换和 key id。换密钥后旧记录不能被新密钥验证。
- 外部 KMS 或非对称签名。
- 远程归档和对象存储。
- 跨段的锚定或公证。

## 证据

- 反例红: `docs/evidence/SLICE-053-audit-rotation-signing.txt`，`AuditSignatureInvalid` ImportError，`AuditPipeline` 不认识 `max_records`，`serve-audit` 参数退出 2
- 实现后绿: 同文件，31 passed；`check.py --fast` ALL PASS（609 passed, 13 skipped），`--full` ALL PASS
- 真实审计服务: 同文件，5 条事件轮转成 2+2+1 三个文件，正确密钥验签通过，错误密钥和篡改的签名都在记录 0 被拒绝
