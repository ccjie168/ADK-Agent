# SLICE-104 会话 RLS 运维收口

状态: gated
依据: ADR-0019 的切片计划。

## 意图（要什么，不写怎么写）

把会话 RLS 的启用、回滚、角色要求和排障写进运维手册，并用两个独立进程做一次隔离实测。不改运行时代码，不改契约。

- 手册说明启用顺序：先建会话表，再以属主角色安装策略，最后带 `--session-tenant-scope --session-rls` 重启。
- 手册写明应用角色必须是表属主、不能是 superuser、不能有 `BYPASSRLS`。superuser 会绕过 RLS，拿它验证是假阳性。
- 手册写回滚：去掉 flag 重启；彻底移除策略要单独评审；不删表。
- 证据记录一次跨进程实测：进程 A 以 `acme` 写入，进程 B 以 `other` 读 0 行，以 `acme` 读到行。安装策略前同一个进程 B 能读到，证明检查有区分度。

## 新增文件

- `docs/specs/SLICE-104-session-rls-ops.md`
- `docs/evidence/SLICE-104-session-rls-ops.txt`

## 修改文件

- `docs/guides/operations.md`（会话存储的租户隔离一节）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`（完成时）

## 完成判据（可执行）

- [x] 手册新增一节，含启用顺序、角色要求、行为、回滚与排障 -> `rg -n "会话存储的租户隔离" docs/guides/operations.md`
- [x] 手册写明 superuser 绕过与 legacy 不可见 -> 同节文本
- [x] 跨进程实测记录在证据文件 -> postgres 段
- [x] `sessions enable-rls` 在属主角色下成功且重复运行成功 -> 证据文件 cli 段
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：`rg -c "会话存储的租户隔离" docs/guides/operations.md` -> 当前 0
- [x] 反例 2：安装策略前，跨进程进程 B 以 `other` 能读到 `acme` 的行 -> 说明隔离检查确实有信号

## 契约（如涉及对外接口）

不涉及。CLI 与存储接口在 SLICE-103 已定。

## 5 问威胁建模（10 分钟）

1. **数据**：会话、事件、用户状态。
2. **调用方**：发布操作员、值守、两个独立应用进程。
3. **信任边界**：属主角色到策略安装，应用角色到行，superuser 到全部。
4. **恶意输入最坏结果**：用 superuser 验证得到假阳性（缓解：手册与测试都要求非 superuser）；legacy 行突然不可见被误判为故障（缓解：手册写明不自动迁移）；回滚时删表丢数据（缓解：手册禁止删表）。
5. **失败是否泄露信息**：排障命令不回显 DSN；策略失败表现为空结果。

## 范围外

- `app_states` 的租户隔离。
- 自动迁移 legacy 会话。
- 每租户数据库或 schema。

## 证据

- 反例红：`docs/evidence/SLICE-104-session-rls-ops.txt` 的 red 段
- 跨进程实测：同文件 postgres 段
- CLI：同文件 cli 段
- 门禁：同文件 gate 段
