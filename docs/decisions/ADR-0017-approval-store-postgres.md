# ADR-0017 审批收件箱的 Postgres 存储

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

ADR-0016 把审计搬进 Postgres，多副本的剩余阻塞项只剩审批。现在的 `FileApprovalInbox` 用两个文件表示一条审批：`<id>.request.json` 与 `<id>.decision.json`，决策靠临时文件加 `os.link` 保证只写一次；执行器提交请求后在进程内轮询决定文件。

这在单机是可靠的，跨主机不成立。共享卷上的 `os.link` 与目录可见性没有一致保证，两个副本可能看到不同状态；文件还会随容器重建丢失。审批卡在执行路径上，重复决策或丢失决策是正确性问题，不是展示问题。

## 决定

1. **一条请求一行，状态机存在行内。** 新表 `adk_approvals`：

   ```text
   request_id text primary key
   tenant text not null
   run_id text not null
   trace_id text not null
   step_id text not null
   agent_ref jsonb not null
   principal jsonb not null
   input text not null
   reason text not null default ''
   requested_at timestamptz not null
   expires_at timestamptz
   status text not null            -- pending | approved | denied | expired | cancelled
   decided_at timestamptz
   decided_by text
   decision jsonb
   ```

   - 提交用 `INSERT ... ON CONFLICT (request_id) DO NOTHING`。相同请求重复提交幂等；同 id 不同内容按 `ApprovalConflict` 拒绝。
   - 决策用 `UPDATE ... WHERE request_id = $1 AND status = 'pending' RETURNING *`。没有返回行时区分“不存在”与“已决策或已过期”，分别映射到 `ApprovalNotFound` 与 `ApprovalConflict`。两个副本同时决策只有一个成功，另一个拿到冲突，与文件实现的独占创建等价。
   - 过期在读取与决策时按 `expires_at < now()` 计算为 `expired`，`pending()` 不返回已过期记录。已经决策的请求即使之后过了截止时间也保持原决定。

2. **等待路径沿用轮询。** `request()` 提交后按 `poll_seconds` 查行，不引入 `LISTEN/NOTIFY`。v1 的请求量远低于轮询能承受的范围，长连接与重连逻辑留到有真实延迟需求时再做。轮询间隔与数据库负载写进文档。

3. **保留与归档对齐文件实现。** `prune(max_age_seconds, archive=True)` 默认把终结记录搬到 `adk_approvals_archive`（同列），`archive=False` 时删除。只处理 `approved`、`denied`、`expired`、`cancelled`，`pending` 永不清除。

4. **v1 不加 RLS。** 与审计一致，租户过滤在服务层：控制台按 token 租户列出，admin 才能跨租户决策。审计表与审批表都靠服务层隔离，这一点进入契约与渗透测试清单。

5. **多副本前提收口。** 审计（ADR-0016）与审批在 Postgres，会话用 `SESSION_URL`，注册表、工件、配额、授权、连接器、peer、远端目录用 Postgres，限流用 Redis。满足这些之后，同一服务可以多副本，文件实现只用于单机与演示。K8s 多副本清单在 099 之后另起切片。

## 切片

- SLICE-098 `PostgresApprovalInbox`：提交、决策、读取、待办、过期与归档，文件实现作为对照；并发决策测试。
- SLICE-099 接线：控制台 `--approval-db`、执行器与 CLI prune，契约与证据收口。
- 之后多副本清单与运维手册。

## 备选与否决

- **共享卷继续用文件**：跨主机 link 与可见性不可靠；否决。
- **`LISTEN/NOTIFY` 唤醒等待者**：延迟更低，但要维护长连接与重连，还会占连接池；v1 否决。
- **请求表与决策表分开**：两行之间需要事务与额外约束，单行状态机更简单；否决。
- **现在就给审批加 RLS**：admin 跨租户决策需要频繁切换上下文，且与审计口径不一致；留作后续加固。

## 后果

- 审批成为共享、原子、可归档的存储，复制与容器重建不再丢状态。
- 决策延迟仍是轮询间隔，不保证即时；执行器侧的超时与取消语义不变。
- 多一条表与一个适配器；文件实现保留，便于单机与回滚。
- 租户隔离依赖服务层，必须在契约与测试里覆盖。

## 确认记录

2026-11-14 会话确认，三点均按本 ADR 采纳：

1. 单行状态机，条件 `UPDATE` 保证决策只生效一次。
2. 等待用轮询，不引入 `LISTEN/NOTIFY`。
3. v1 不加 RLS，归档进同列结构的兄弟表；多副本清单放在接线之后。
