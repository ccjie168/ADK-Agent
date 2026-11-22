# ADR-0040 全局默认模型配置与动态切换

状态: Accepted   日期: 2026-11-22   签字: Jie CAO（会话确认）

## 背景

平台当前的模型选择是「启动时确定」的：`build_model()` 读 `ADK_AGENT_MODEL` 环境变量，缺省回落到
`litellm:deepseek/deepseek-v4-pro`；manifest 的 `model_policy`（`provider_allowlist` / `model_allowlist`）
是发布时锁死的约束，不选模型。管理员要换模型，只能改环境变量并重启进程。

用户需要的是：**管理员在控制台里控制全局默认模型，改了动态生效**——不重启、新会话/新请求立即用
新模型。这是平台「模型网关」配置面的运行时化，和 ADR-0033（模型别名路由，发布时在 manifest 里声明的
别名）是互补的：本 ADR 管「全局默认选哪个模型」，ADR-0033 管「某个 agent 的别名怎么路由」。

## 决定

### 1. 全局默认模型是一个平台级配置

配置就是一个短字符串，沿用 `build_model` 的 provider 前缀语法（`litellm:deepseek/deepseek-v4-pro`、
`claude:claude-sonnet-5-5`、`gemini:gemini-2.5-pro`）。它只决定「无显式 spec 时 `build_model()` 用哪个
模型」，不改 manifest 的 `model_policy` 约束语义。

优先级，从高到低：

1. `build_model(spec)` 的显式 `spec`（agent 代码里写死的）。
2. **全局默认模型**（本 ADR 引入的运行时配置）。
3. `ADK_AGENT_MODEL` 环境变量。
4. 既有 fallback（`GOOGLE_API_KEY`/`GEMINI_API_KEY` → gemini，否则 `litellm:deepseek/deepseek-v4-pro`）。

### 2. 动态生效用「内存 override + 持久化 store」两层

`build_model` 是同步函数，不能 await 数据库。所以拆两层：

- **内存 override**：`models` 模块级变量 `_default_model_override`，`set_default_model(spec)` 同步更新。
  `_default_model_config()` 优先读它。管理员改配置后，当前进程新构建的 model 立即用新值。
- **持久化 store**：`ModelConfigStore` 协议（`get` / `put`），文件 + Postgres 双后端（复用 registry 的
  `safe_join` / `LazyPool` 模式），用于跨重启持久化。进程启动时读 store 初始化 override。

多副本实时同步属第二阶段：MVP 单副本内存 override 即动态生效；跨副本一致性后续用「Postgres store +
通知/轮询」补齐，本 ADR 不承诺。

### 3. 控制台暴露只读 + 管理员写路径

- `GET /api/model-config`：返回当前全局默认模型（`{"model": "litellm:deepseek/deepseek-v4-pro"}`）。
  新增能力 `model.read`，映射给 `admin` 与 `operator`/`ops`/`approver`（运维角色），基础角色与
  publisher 看不到。这跟 `policy.read` 一个道理：平台运行配置按 role-based 可见，不默认全开。
- `PUT /api/model-config`：admin-only，请求体 `{"model": "<provider>:<name>"}`，校验 provider 前缀合法、
  写 store + 更新内存 override，写审计 `model.configure`。
- 模型面板（SLICE-225 的只读面板）加一个「设置默认模型」输入框与按钮，按钮只对 admin 显示。

## 备选与否决

- **只改环境变量、重启生效。** 最简单，但不满足「动态生效」的核心诉求。否决。
- **per-agent 模型配置。** 灵活，但复杂，且 manifest `model_policy` 已是发布时约束。留作第二阶段。
- **模型别名路由（ADR-0033 的运行时化）。** 复用现有别名机制，但需要别名 store 与运行时解析的
  完整改造，MVP 用不上。留作第二阶段。
- **每次 `build_model` 同步读文件 store。** 多副本天然一致，但每次构建都落盘读取、且文件 store 同步
  读接口要新写。MVP 用内存 override 更简单，代价是单副本。

## 后果

- 管理员无需重启即可切换全局默认模型，新会话/新请求动态生效。
- 新增 `ModelConfigStore` 协议与文件/Postgres 双实现、`models` 的 `set_default_model` / override 读取、
  控制台 `/api/model-config` 读写端点与模型面板的管理员入口。
- 不改变 manifest `model_policy` 的约束语义，不改变 `build_model(spec)` 显式 spec 的优先级。
- 多副本下「一个进程改、所有进程生效」不在 MVP，是明确记录的第二阶段缺口。

## 切片（MVP，待连续执行）

1. **模型配置类型与 store**：`ModelConfigStore` 协议 + 文件/Postgres 双实现，`set_default_model` /
   `_default_model_config` 读 override，优先级 2/3/4 落地。
2. **控制台端点 + 管理员 UI**：`GET/PUT /api/model-config`，模型面板加「设置默认模型」，admin 按钮显隐，
   写审计 `model.configure`。
3. **验收**：`prove_it_works` 断言「改配置后新 chat 用新模型」，pytest 覆盖优先级与权限。

## 确认记录（2026-11-22 会话确认）

1. 接受「全局默认模型 + 内存 override + 持久化 store」的两层设计。
2. 接受「MVP 单副本动态生效，多副本同步属第二阶段」。
3. 接受 `GET /api/model-config` 走 `model.read`（admin + operator）、`PUT` admin-only 的 role-based 权限。
