# ADR-0016 审计存储后端与多副本前提

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

方向评审 Phase E 要把平台自身跑稳。现状里大多数状态已经有共享后端：注册表、评测报告、生命周期、工具授权、连接器、peer、远端目录、配额与工件都有 Postgres 实现，限流可走 Redis。真正挡在多副本前面的是审计与审批。

审计现在有两种形态：进程内写 JSONL，或发给审计服务，服务再写 JSONL。单机没问题，多副本就会出两类问题。文件没有跨主机的原子追加，哈希链会被并发写坏；审计读路径也只有本地文件或单个服务。审批收件箱仍是文件，决策靠独占创建文件保证唯一，跨主机不成立。

哈希链是审计的防篡改属性。多写者设计必须保住它，不能为了并发把链拆散得无法验证。

## 决定

1. **审计进 Postgres，保留每租户一条哈希链。** 现有 JSONL 实现就是按租户分链（`prev_hash` 取该租户的上一条），Postgres 版必须与它一致。新表 `adk_audit_records`：

   ```text
   tenant text not null
   sequence bigint not null
   event jsonb not null
   prev_hash text not null
   hash text not null
   signature text
   kid text
   action text not null
   status text not null
   trace_id text not null
   run_id text not null
   occurred_at timestamptz not null
   primary key (tenant, sequence)
   ```

   写入在事务内先取 `pg_advisory_xact_lock(hashtext('adk_audit:' || tenant))`，读该租户最后一条的 `hash` 与 `sequence`，复用现有 `record_hash` 与 `record_signature` 算出新记录再插入。同租户的并发写被串行化，不同租户互不阻塞；链语义与现有 `verify_audit_file` 完全一致。吞吐以租户内锁为上限，实验值写进证据，不承诺随副本线性扩展。

2. **共享写与读各实现一份。** `PostgresAuditSink` 实现 `AuditSink`，`PostgresAuditQuery` 实现 `AuditQuery`，过滤条件与限额和现有 `query_events` 一致。`verify-audit` 增加数据库模式，按 `sequence` 遍历整条链并校验签名。服务、控制台与网关通过 `--audit-db`/`AUDIT_DATABASE_URL` 选择后端；不配时保留 JSONL，单机与演示继续可用。

3. **v1 不给审计表加 RLS。** 租户过滤仍在服务层：`/v1/events` 与非 admin 控制台按 token 租户过滤，admin 才能跨租户。原因是审计服务自身要做跨租户查询与验链，RLS 会让这两条路径都要切换租户上下文。把这一点写进契约与威胁模型，R L S 留作后续加固。

4. **多副本的前提列清楚。** 同一服务多副本之前必须满足：审计在 Postgres（本 ADR），审批在 Postgres（后续 ADR），会话用 `SESSION_URL` 外置（已支持），注册表、工件、配额、工具授权、连接器、peer 与远端目录用 Postgres，限流用 Redis。文件实现只保留给单机与演示，不作为共享卷方案。

5. **部署姿态。** 不依赖共享卷；就绪检查包含状态后端；优雅停机后退出；审计写锁是全局串行点，副本数增加不提高审计写吞吐。K8s 多副本清单排在审批存储之后，另起切片，并带回到文件模式的回滚说明。

## 切片

- SLICE-096 链逻辑抽成可复用函数，`PostgresAuditSink` 与 `PostgresAuditQuery`，`verify-audit --audit-db`，Postgres 集成测试与并发写测试。
- SLICE-097 服务、控制台与网关接线，契约与证据收口；文件模式回归验证。
- 之后另起 ADR 设计审批的 Postgres 存储，再做多副本清单。

## 备选与否决

- **每个写者一条链**：并发好，但验证要按写者分片，运维心智模型和现有 `verify-audit` 都要改；v1 否决，留作规模上来后的演进。
- **不存链，只靠数据库完整性**：丢掉防篡改属性；否决。
- **审计服务单写，其他副本只读**：仍然要一个高可用单写者，复杂度不低于锁；否决。
- **共享卷上继续写 JSONL**：跨主机追加与锁不可靠；否决。
- **只把审计转发到外部 SIEM**：不替代本地受治理的存储与验链；否决。

## 后果

- 审计成为共享、可查询、可验链的存储，多副本写安全但写吞吐受锁限制。
- 多一条 Postgres 表与两个适配器；文件模式保留，便于单机与回滚。
- 审计表 v1 没有 RLS，租户隔离依赖服务层，必须在契约与渗透测试里覆盖。
- 审批仍是多副本的剩余阻塞项，另起 ADR。
- 现有 JSONL 历史不自动导入；旧文件继续用 `verify-audit` 验证，新事件从切换点进库。

## 确认记录

2026-11-14 草拟，待会话确认三点：

1. 每租户一条哈希链，加按租户的 advisory lock，不做每写者分链。草稿曾写成“单一全局链”，与实际 JSONL 实现的按租户分链不符，确认后按代码事实更正。
2. Postgres 写读适配器按 URL 选择，文件模式保留。
3. v1 审计表不加 RLS，租户过滤留在服务层；多副本等审批存储的 ADR。
