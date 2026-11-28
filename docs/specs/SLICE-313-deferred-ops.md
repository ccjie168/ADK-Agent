# SLICE-313 延迟审批的运维收口（ADR-0049 切片 4）

状态: active
依据: ADR-0049 决定 7、8 与切片 4

## 意图

1. 恢复时拒绝已过期的决定，不再执行过期步骤。
2. 文件部署的单赢家：恢复器支持 `claim_dir`，独占锁文件保证一次决定只恢复一次。
3. 运维手册 `docs/guides/deferred-approvals.md`：组件、开启方式、单赢家覆盖范围
   （文件有、Postgres 多副本没有）、到期、通知、观测与常见故障。

## 契约（先改）

`docs/guides/deferred-approvals.md` 新增；要点：

- `ApprovalResumer(..., claim_dir=DIR)`：对每个 request id 用
  `os.O_CREAT|O_EXCL` 建 `.resume-<id>.lock`；未抢到的进程计入 `skipped`。
  request id 必须匹配 `[A-Za-z0-9._-]{1,128}`，否则 `ValueError`。
- 执行器在采纳决定前比较 `expires_at`：已过期则记 `approval_timeout` 并抛
  `ApprovalTimeout`，不执行该步骤。
- Postgres 多副本的跨主机单赢家是已知缺口，接多副本前要加数据库条件抢占。

## 完成判据

- [ ] 过期决定不被采纳 -> `test_expired_decision_is_not_resumed`
- [ ] 两个恢复器共享 claim 目录时只有一个执行 -> `test_claim_dir_allows_one_winner`
- [ ] 不安全的 request id 被拒 -> `test_claim_rejects_unsafe_request_ids`
- [ ] 手册覆盖组件、开启、单赢家与到期 -> `test_runbook_documents_deferred_approvals`
- [ ] `--full` 门禁通过

## 反例

实现前执行器不检查 `expires_at`、恢复器没有 `claim_dir`、手册不存在；前三条用例失败，
文档用例失败。

## 5 问威胁建模

1. **数据**：锁文件只有 request id；手册不含密钥。
2. **调用方**：恢复器在服务进程内；锁文件在本地目录。
3. **信任边界**：claim 目录与审批目录同属运维可控路径；request id 白名单防路径穿越。
4. **恶意输入**：非法 request id 直接报错，不落盘。
5. **失败是否泄露信息**：错误只带步骤 id 或 request id。

## 范围外

- Postgres 跨主机条件抢占（记录为缺口）。
- 指标接入 Prometheus（本期只暴露计数字段）。

## 证据

- `docs/evidence/SLICE-313-deferred-ops.txt`
