# ADR-0041 控制台产品化 UI + Vue 前端

状态: Accepted   日期: 2026-11-23   签字: Jie CAO（会话确认）

## 背景

控制台当前是写在 `src/adk_agent/console.py` 里的单文件内联 HTML/CSS/JS（零框架，ADR-0039 定的）。
它已经承载了约 20 个面板，但内联字符串已经 5000+ 行，越加越难维护。用户提出 6 条产品化诉求，
并明确要求「前端用框架、未来好扩展」，建议 Vue：

1. 不同用户一个登录入口，按 role-based 权限看到不同 view。
2. 左导航按 agent 旅程组织：agent 总览、注册数、lifecycle 状态、版本等。
3. agent 开发用模板式引导（向导）。
4. MCP 与 API 生态的展示方式。
5. 安全合规与审计的管理。
6. 用户与不同角色定义权限的配置和管理。

## 决定

### 1. 技术栈

- 框架 Vue 3（Composition API），构建 Vite，路由 Vue Router 4，状态 Pinia（按需），语言 TypeScript。
- 前端是一个独立的 SPA，Vite 构建产出静态资源（`dist/`），FastAPI 用 `StaticFiles` 挂载到 `/`。
- 后端接口不变：继续走现有 `/api/*` JSON；鉴权沿用现状（bearer token 或 OIDC PKCE），token 仍存
  浏览器 `sessionStorage`。SPA 只替换「渲染层」，不重写后端。

### 2. 集成与迁移

- 新 SPA 与旧内联控制台**先并行**：`console` 命令加开关选择渲染来源，默认先走旧控制台，SPA 逐步接管。
- 每迁一个面板就切一个开关位，全部面板迁完 + 新功能落地后，删除 `_INDEX_HTML` 内联渲染，收敛为单一 SPA。
- 构建产物纳入版本控制或 CI 产出；部署时 FastAPI 直接服务 `dist/`，不再需要运行时构建。

### 3. 角色/授权模型（阶段 1 的关键设计点）

现在角色→能力是代码硬编码（`_CAPABILITIES_*`），用户来源是 `--role`（dev）或 OIDC claim（生产）。
阶段 1 把它运行时化：

- **角色定义**：一个角色 = 一个命名能力集合，落持久化 store（文件/Postgres 双后端，复用 registry 的
  `safe_join`/`LazyPool` 模式）。内置角色（admin/operator/ops/approver/publisher/developer/base）作为
  默认种子，保持向后兼容。
- **用户绑定**：用户（`subject`，来自 OIDC claim 或本地 dev 主体）→ 一个或多个角色。
- **能力解析**：`_capabilities_for(roles)` 改为「读角色定义 store，角色名 → 能力集合的并集」；未定义
  角色回落基础能力。写路径（admin-only 的 `*manage`）仍由能力集合天然约束，不单独硬编码 admin。
- **管理界面**：新增「用户/角色」面板，admin 可增删角色、给角色勾选能力、给用户绑定/解绑角色；
  写审计 `role.define` / `user.bind`。
- **安全边界**：只有 `admin` 能改角色/用户绑定；角色 store 缺后端时 fail-closed（所有未定义角色回落
  基础能力，admin 也失去管理权限，而不是放行）。

### 4. 五阶段切片

- **阶段 0：Vue 地基 + 平价迁移**。脚手架 Vue+Vite+Router+Pinia+TS，FastAPI `StaticFiles` 挂载，SPA
  鉴权流，把现有约 20 个面板逐一迁到 Vue（行为等价，不含新功能），双渲染并存，`prove_it_works` 的
  P13 继续断言控制台基线。
- **阶段 1：用户/角色/授权管理 + 统一登录**（诉求 1+6）。角色定义 store + 用户绑定 store + 能力解析
  运行时化 + 管理面板。
- **阶段 2：Agent 中心总览**（诉求 2）。把 registry/lifecycle 数据重组成 agent 旅程视图：注册数、
  lifecycle 分布、版本、评测、跨租户/远端目录。
- **阶段 3：安全合规聚合视图**（诉求 5）。聚合审计完整性、安全扫描（CodeQL/依赖漏洞）、密钥轮换状态、
  策略概览。
- **阶段 4：MCP/API 生态展示**（诉求 4）。统一展示 MCP server、A2A 对端、连接器、可复用工具，带接入
  引导。
- **阶段 5：Agent 开发向导**（诉求 3）。把 CLI `compose` 模板做成多步 UI 向导（名称/版本/租户/指令/
  工具/数据类/发布）。

每阶段独立 spec + 契约 + 红测 + 门禁 + 独立验证，与既有切片流程一致。

## 备选与否决

- **继续零框架**：能省一条 Node 构建链，但 6 条诉求里的向导/表格/配置表单会让内联 JS 更难维护，且
  用户明确要框架。否决。
- **React**：生态更大，但样板多、JSX 心智重，单人维护成本高。否决。
- **Svelte**：更轻，但生态小、招人/找资料难。否决。
- **CDN 挂 Vue（无构建）**：省构建链，但拿不到 SFC/TS/Vite 的工程化，长期扩展受限。否决。
- **前后端不分离（模板渲染）**：与「可扩展框架」诉求相悖。否决。

## 后果

- 新增前端依赖（Vue/Vite/Router/Pinia/TS 工具链），npm 侧安全扫描与现有 pip-audit 平行，`dist/` 产物
  纳入发布物。
- 控制台不再是「单 Python 字符串」，部署多一步前端构建；本地开发用 Vite dev server 代理到 FastAPI。
- 后端 `/api/*` 与鉴权不变，风险集中在渲染层迁移与「双渲染并行」期的一致性。
- 阶段 1 的角色/授权 store 是唯一牵动后端安全模型的改动：改完要重跑 `prove_it_works` 确认权限语义
  未回归。

## 确认记录（2026-11-23 会话确认）

1. 接受 Vue 3 + Vite + Vue Router 4 + Pinia + TypeScript 技术栈。
2. 接受 SPA 分离、FastAPI `StaticFiles` 挂载、后端 `/api/*` 与鉴权不变。
3. 接受「新 SPA 与旧内联控制台先并行、迁完删除」的迁移策略。
4. 接受五阶段 + 阶段 0（Vue 地基与平价迁移）的切片顺序。
5. 接受阶段 1 的角色/授权 store 设计方向（持久化角色→能力 + 用户绑定、内置角色种子、fail-closed）。
