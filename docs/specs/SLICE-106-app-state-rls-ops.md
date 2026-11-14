# SLICE-106 应用级状态 RLS 运维收口

状态: gated
依据: ADR-0020 的切片计划。

## 意图（要什么，不写怎么写）

把第四张表、`app_name` 前缀和旧数据影响写进运维手册，并用两个独立进程验证 `app_states` 的隔离。不改代码。

- 手册的范围从三张表改成四张，`app_states` 用 `app_name` 前缀策略。
- 启用顺序写明 `app_name` 变成 `<tenant>:<agent>`，以及旧会话与旧应用级状态会读不到，需要迁移或丢弃。
- 排障增加应用级状态的检查项。
- 证据记录跨进程实测：进程 A 以 acme 写入，进程 B 以 other 读会话 0 行、应用级状态 0 行，以 acme 读到。

## 新增文件

- `docs/specs/SLICE-106-app-state-rls-ops.md`
- `docs/evidence/SLICE-106-app-state-rls-ops.txt`

## 修改文件

- `docs/guides/operations.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`（完成时）

## 完成判据（可执行）

- [x] 手册标题含 ADR-0020，范围写四张表 -> `rg -n "ADR-0019、ADR-0020" docs/guides/operations.md`
- [x] 启用顺序写明 `app_name` 前缀与旧数据决定 -> 同节第 6 步
- [x] 排障含应用级状态 -> 同节排障列表
- [x] 跨进程实测记录在证据文件 -> postgres 段
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：`rg -c "ADR-0020" docs/guides/operations.md` -> 改前 0
- [x] 反例 2：`rg -n "app_states 不在范围内" docs/guides/operations.md` -> 改前有这一条，现已删除

## 契约（如涉及对外接口）

不涉及。SLICE-105 已更新 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：会话、事件、用户状态、应用级状态。
2. **调用方**：发布操作员、值守、两个独立应用进程。
3. **信任边界**：属主角色到策略安装，应用角色到行，superuser 到全部。
4. **恶意输入最坏结果**：升级后旧会话突然不可见被误判为故障（缓解：手册写明不自动迁移）；用 superuser 验证得到假阳性（缓解：角色要求）；回滚时删表丢数据（缓解：手册禁止删表）。
5. **失败是否泄露信息**：排障命令不回显 DSN；策略失败表现为空结果。

## 范围外

- legacy 会话与应用级状态的自动迁移。
- 每租户数据库或 schema。

## 证据

- 反例红：`docs/evidence/SLICE-106-app-state-rls-ops.txt` 的 red 段
- 跨进程实测：同文件 cross-process 段
- 门禁：同文件 gate 段
