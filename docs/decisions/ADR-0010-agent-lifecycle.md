# ADR-0010 Agent 版本生命周期

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

ADR-0009 把已发布版本放进共享注册表，版本不可变、按 digest 固定。发布是纯追加的：一个版本发布后没有下线、废弃、回滚的路径。现在能做的只有发布新版本并指望调用方换引用，旧版本永远可加载、可运行。

这带来三个具体问题。有问题的版本无法止血。市场页没有“已废弃”信号，用户可能选中旧版本。审计和运营视图按版本聚合，但没有“这个版本何时停、谁停的”记录。

方向评审把“注册、维护和运行”列为平台核心能力，生命周期缺的正是“维护”。ADR-0009 已把生命周期显式排在 ADR-0010。

不决定的后果：版本只会增加不会收敛，试点扩大后无法负责任地下线任何东西。

## 决定

1. **三态，退役为终态。**

   | 状态 | 含义 | 是否可加载 |
   | --- | --- | --- |
   | `published` | 默认，发布即此态 | 是 |
   | `deprecated` | 仍可用，市场页给警告 | 是 |
   | `retired` | 停止新加载与新启动 | 否 |

   允许的转换：`published → deprecated`、`published → retired`、`deprecated → published`（撤销废弃）、`deprecated → retired`。`retired` 是终态，不能回到其他状态；要复活内容，发布新版本。对同一状态的重复设置是幂等的，不改 `changed_at`。

2. **状态独立存储，不改已发布记录。**

   ```sql
   CREATE TABLE adk_agent_lifecycle (
       tenant text NOT NULL,
       agent_id text NOT NULL,
       version text NOT NULL,
       status text NOT NULL,
       changed_at timestamptz NOT NULL,
       changed_by text NOT NULL,
       reason text NOT NULL DEFAULT '',
       PRIMARY KEY (tenant, agent_id, version)
   );
   ```

   没有行就是 `published`。`PublishedAgent`、manifest 摘要和工件摘要都不变，已发布记录的 digest 语义不受影响。状态变化写一条 `agent.lifecycle` 审计，带 from/to 与 reason，历史以审计为准；表里只保留当前状态。

   文件注册表保留单机演示实现，状态写在 `<registry>/<tenant>/<id>/<version>.lifecycle.json`，与 Postgres 行为一致。

3. **控制面接口。**

   - `GET /v1/agents/{tenant}/{id}/{version}/lifecycle`：返回当前状态与变更信息。没有行时返回 200 和 `status=published`。
   - `PUT /v1/agents/{tenant}/{id}/{version}/lifecycle`：请求体 `{"status": "deprecated"|"retired"|"published", "reason": "..."}`。版本必须已发布，否则 404。非法转换（例如 `retired → published`）返回 409 `invalid_transition`。只有 admin 或静态 token 操作者可以改状态；OIDC 非 admin 返回 403。
   - `GET /v1/agents` 与单条读取增加只读字段 `lifecycle`（`status`、`changed_at`、`changed_by`）。这是服务层附加字段，不改 `PublishedAgent` 契约。
   - 发布新版本（`POST /v1/agents`）不写生命周期行，视为 `published`。

4. **退役只拦新加载，不中断已运行会话。**

   - `POST /api/registry/load` 加载退役版本返回 409 `version_retired`。
   - `console`/`serve`/`serve-many --agent-ref` 解析到退役版本时启动失败，退出 1。
   - 已加载进进程的 agent 继续服务到进程重启，不强制中断。这一点写进契约，避免假装能即时消失。
   - 市场页对 `deprecated` 显示警告徽标，对 `retired` 禁用 Open chat 并说明原因。

5. **命令与客户端。**

   - `adk-agent lifecycle set --registry-url URL --tenant T --id ID --version V --status S [--reason TEXT]`，或 `--registry DIR` 走文件实现。
   - `HttpAgentRegistry` 增补 `lifecycle(...)` 与客户端类型；控制台用同一接口。
   - `serve-registry` 自动配置 Postgres 生命周期存储，不需要额外参数。

6. **退役不是删除。** 记录、工件字节与评测报告都保留；GC 与保留策略不在本 ADR。

## 备选与否决

- **把状态放进 `PublishedAgent` 并重算摘要**：破坏“发布即不可变”和 digest 固定，已发布工件与记录会失效；否决。
- **直接删除记录与工件**：丢失审计证据，且正在运行的引用会断；否决。
- **追加式生命周期事件表，当前状态取最后一条**：历史更完整，但每次读取都要聚合，v1 用单行加审计；等控制面需要完整变更列表时再演进。
- **退役即刻中断已运行会话**：需要运行时反向通知与进程间协调，超出本 ADR；先接受进程重启前仍可用，并在契约里写明。

## 后果

- 版本可以收敛。运营能先废后停，市场页有明确信号，审计里有操作者与原因。
- 生命周期是可变元数据，数据库需要写权限；与不可变的版本表分开，互不影响。
- 多副本看到同一状态，因为状态在共享存储里；文件实现只服务单机。
- 退役后已运行的进程仍能服务一段时间，这是已知窗口，不是缺陷。
- 后续切片：存储与 API、控制台与加载拦截、市场页徽标、CLI 命令。回滚与保留策略另立 ADR。

## 确认记录

2026-11-14 会话确认，三点均按本 ADR 采纳：

1. 三态与转换规则，`retired` 为终态，`deprecated` 可撤销。
2. 独立表 `adk_agent_lifecycle`（文件实现对应 `<version>.lifecycle.json`），缺行视为 `published`，历史以 `agent.lifecycle` 审计为准。
3. 退役只阻止新加载与新启动，不中断已运行会话；加载退役版本返回 409 `version_retired`。
