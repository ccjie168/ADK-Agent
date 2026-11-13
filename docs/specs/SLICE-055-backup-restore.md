# SLICE-055 文件状态备份与恢复

状态: merged
依据: SLICE-012，SLICE-045，SLICE-053，`docs/contracts/cli.md`

## 意图（要什么，不写怎么写）

注册表、审批收件箱和审计文件都只在本地磁盘上，没有统一的备份和恢复入口。这一刀加一个可重复的备份包格式和对应的恢复命令。

- 新增 `src/adk_agent/backup.py`：`create_backup`、`restore_backup`、`BackupError`、`BACKUP_VERSION`。
- 包是 gzip tar。归档内前缀固定为 `registry/`、`approvals/`、`audit/`。审计来源会连同数字后缀的轮转段一起打包。
- 包内有 `manifest.json`，记录版本、创建时间、每个来源的文件数和字节数。
- 创建成功后算归档的 sha256 并打印。POSIX 上把文件权限设为 0600。
- 恢复先解到目标旁边的临时目录，校验 manifest 后整体替换目标。解包用 `tarfile` 的 `filter="data"`，拒绝绝对路径和 `..`。任何失败都清掉临时目录，不留半成品。
- 目标已存在且非空时拒绝，除非 `--force`。`--force` 也走临时目录，成功后才替换。
- CLI 新增 `backup` 和 `restore` 两个子命令。

Postgres 里的会话和配额不在这一刀里，继续用 `pg_dump`。运行中的服务写审计文件时，最后一行可能是半条；校验会指出断链，这一点写进文档。

## 新增文件

- `src/adk_agent/backup.py`
- `tests/test_backup.py`
- `tests/test_cli_backup.py`
- `docs/evidence/SLICE-055-backup-restore.txt`

## 修改文件

- `src/adk_agent/cli.py`：`backup` 和 `restore` 子命令
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
BACKUP_VERSION = 1

manifest.json:
  {
    "version": 1,
    "created_at": "<ISO-8601>",
    "sources": [
      {"kind": "registry", "files": 3, "bytes": 1200},
      {"kind": "approvals", "files": 2, "bytes": 800},
      {"kind": "audit", "files": 4, "bytes": 4000}
    ]
  }

归档布局:
  registry/<relative paths>
  approvals/<relative paths>
  audit/<file name and .NNNNNN segments>
  manifest.json
```

`create_backup(out, sources)`：

- `sources` 是 `(kind, path)` 序列，`kind` 只能是 `registry`、`approvals`、`audit`。
- registry 和 approvals 递归加目录；audit 加文件本身和同名前缀的数字段。
- 先写内容，最后写 manifest。返回 manifest 和归档 sha256。

`restore_backup(archive, dest, *, force=False)`：

- dest 存在且非空且没有 force -> `BackupError`。
- 解到 `dest.parent` 下的临时目录，`filter="data"`。
- manifest 缺失或版本不是 1 -> `BackupError`。
- 成功后替换 dest，返回 manifest。

## 完成判据（可执行）

- [x] 备份再恢复内容一致 -> `tests/test_backup.py::test_roundtrip`
- [x] manifest 记录来源计数 -> `tests/test_backup.py::test_manifest_counts`
- [x] 审计段一起打包 -> `tests/test_backup.py::test_audit_segments_included`
- [x] 非空目标被拒 -> `tests/test_backup.py::test_restore_refuses_nonempty`
- [x] force 可以替换 -> `tests/test_backup.py::test_restore_force_replaces`
- [x] 路径穿越被拒且不留文件 -> `tests/test_backup.py::test_restore_rejects_traversal`
- [x] 缺 manifest 被拒 -> `tests/test_backup.py::test_missing_manifest_rejected`
- [x] 未知来源类型被拒 -> `tests/test_backup.py::test_unknown_kind_rejected`
- [x] CLI 备份输出路径和哈希 -> `tests/test_cli_backup.py::test_cli_backup`
- [x] CLI 恢复输出文件数 -> `tests/test_cli_backup.py::test_cli_restore`
- [x] CLI 没有来源退出 1 -> `tests/test_cli_backup.py::test_cli_backup_requires_source`
- [x] CLI 非空目标退出 1 -> `tests/test_cli_backup.py::test_cli_restore_refuses_nonempty`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.backup import create_backup` -> 当前 `ImportError`
- [x] 反例 2：`adk-agent backup --out x.tar.gz` -> 当前 argparse 退出 2
- [x] 反例 3：`adk-agent restore --archive x --dest y` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/cli.md`。已加 `backup` 和 `restore` 两节。

## 5 问威胁建模（10 分钟）

1. **数据**：注册表文件、审批请求和决定（含待审输入）、审计事件和段文件、归档本身。
2. **调用方**：运维和定时任务。
3. **信任边界**：命令行到文件系统，归档文件到恢复目录。
4. **恶意输入最坏结果**：恶意归档写出目标目录（路径穿越或绝对路径）；覆盖非空目录；备份文件权限过宽泄露待审输入；备份中途服务写入导致半个文件。缓解是 `filter="data"`、目标必须为空或显式 `--force`、POSIX 0600、临时目录加原子替换。备份不含 Postgres 数据。
5. **失败是否泄露信息**：错误只报类名和来源类型，不输出文件内容。manifest 不含路径以外的业务数据。

## 范围外

- Postgres 会话和配额的备份。用 `pg_dump`。
- 加密和密钥管理。归档权限靠文件系统。
- 增量备份、远端对象存储和保留策略。
- 在线一致性快照。运行中的审计文件可能截到半行，校验会报断链。

## 证据

- 反例红: `docs/evidence/SLICE-055-backup-restore.txt` 的 red 段
- 实现后绿: 同文件 green 段，12 passed
- 实机: 同文件 live 段，备份哈希与 `sha256sum` 一致、`.bak` 被排除、恢复 5 个文件、非空目标退出 1、`--force` 清掉哨兵文件
