# ADR-0011 工具授权申请与临时授权

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

工具授权的唯一来源是 `AgentManifest.tool_grants`。它随版本发布固定，改授权就要发布新版本。这在稳定期是对的，但运行期没有第二条路径：agent 撞到未授权工具时只能报错，运维要加一个临时工具得走一次完整发布，评测门禁也得重跑。

生命周期（ADR-0010）解决了“版本能不能用”，没有解决“这个版本能不能临时用某个工具”。工具目录（SLICE-075）只读地展示了既有授权，没有申请入口。

要求 4 明确要“有授权和监管和治理机制”。缺的是运行期授权的申请、审批、到期与拒绝闭环。

## 决定

1. **授予以已发布版本为锚。** 申请绑定 `(tenant, agent_id, version, digest)`，不是 agent 名字。同一 agent 的另一个版本或另一个 digest 不会继承临时授权。`retired` 版本不接受新申请。

2. **两种来源合并，默认拒绝。** 运行时先看 manifest 的 `tool_grants`（长期授权），再查临时授权表（已批准且未过期）。任一允许即允许。未命中、已过期、已拒绝一律拒绝。临时授权只覆盖 `tool_id`；数据分级的强制执行不在本 ADR，沿用现状。

3. **申请状态机。**

   | 状态 | 含义 |
   | --- | --- |
   | `pending` | 待审批 |
   | `approved` | 已批准，带 `expires_at` |
   | `denied` | 已拒绝，终态 |
   | `expired` | 超过 `expires_at`，只读终态 |
   | `cancelled` | 申请人撤回，终态 |

   `pending` 必须带 `expires_at`，默认 24 小时，最长 7 天；超过 `expires_at` 未审批视为 `expired`。`approved` 的临时授权最长 7 天，到期即拒绝。终态不可变。

4. **存储与审批入口。**

   ```sql
   CREATE TABLE adk_tool_grant_requests (
       request_id text PRIMARY KEY,
       tenant text NOT NULL,
       agent_id text NOT NULL,
       version text NOT NULL,
       digest text NOT NULL,
       tool_id text NOT NULL,
       data_classes text[] NOT NULL DEFAULT '{}',
       reason text NOT NULL,
       status text NOT NULL,
       requested_by text NOT NULL,
       requested_at timestamptz NOT NULL,
       expires_at timestamptz NOT NULL,
       decided_by text,
       decided_at timestamptz,
       decision_reason text NOT NULL DEFAULT ''
   );
   ```

   文件实现在 `<state>/tool-grants/<request_id>.json`，用于单机开发。控制台提供 `GET /api/tool-grants`、`POST /api/tool-grants`、`POST /api/tool-grants/{id}/decide`；只有 admin 能审批，非 admin 只能对自己的租户申请与查看。申请与决定各写一条审计（`tool_grant.request`、`tool_grant.decide`）。

5. **运行时只读查询，不加缓存（v1）。** `ToolGuard` 的策略引擎在有临时授权存储时，每次 `tool.call` 前按 `(tenant, id, version, digest, tool_id)` 查一次已批准且未过期的授权。工具调用频率低，查询是单行索引读；v1 不加缓存，避免撤权延迟。存储不可达时拒绝（fail closed），并给现有 `tool.call` 审计写 `status=denied`、`error_code=grant_store_unavailable`。

6. **配置。** `console`、`serve`、`serve-many` 接受 `--tool-grants-dir DIR` 或 `GRANT_URL`（Postgres），与配额、审计的配置方式一致。不给时只按 manifest 授权，行为不变。

7. **命令。** `adk-agent tool-grants list|request|decide`，支持文件目录与控制面 HTTP；审批仍要求 admin。

8. **不做**：自动续期、按工具委派审批人、数据分级强制执行、对外 IdP 对接、授权回收扫描任务。过期由读取时判断，不跑后台任务。

## 备选与否决

- **把临时授权写回 manifest 并发布新版本**：要重跑评测、改 digest、产生版本碎片；临时授权本来就该短命，否决。
- **运行时缓存授权**：撤权有延迟且多副本不一致；v1 用单行查询，否决缓存。
- **复用审批收件箱**：现收件箱绑定计划步骤与 run_id，语义不同，混用会污染两条审计链；新表更清楚。
- **到期靠后台清理**：多一个需要保证存活的进程；读取时判断到期足够。

## 后果

- 运行期可以临时放行工具，审批、原因、到期都留痕，过期自动失效。
- 每次工具调用多一次存储查询；存储故障时工具调用被拒绝，这是有意的闭锁。
- 控制台多一个工具授权面板；admin 的审批负担增加，但不引入新角色。
- 后续切片：类型与存储、运行时合并、控制台与命令。数据分级强制与授权回收另立 ADR。

## 确认记录

2026-11-14 会话确认，三点均按本 ADR 采纳：

1. 临时授予以 `(tenant, id, version, digest)` 为锚，与 manifest 授权合并，过期或缺失一律拒绝，`retired` 版本不接受申请。
2. 请求状态机 `pending/approved/denied/expired/cancelled`，待审与有效授权都带 `expires_at`（默认 24 小时，最长 7 天），存 Postgres（文件实现用于开发）。
3. 运行时每次工具调用查询、不加缓存、存储不可达时拒绝；审批入口在控制台与 CLI，只有 admin 能批，申请与决定写审计。
