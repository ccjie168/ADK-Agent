# SLICE-117 角色视图与能力清单

状态: gated
依据: ADR-0022 第 1 条。控制台把 11 个面板展示给所有登录用户，前端不读取角色，越权操作在点击后才收到 403。四类角色与现有导航分组基本重合，缺的是一份服务端能力清单与按能力显示。

## 意图（要什么，不写怎么写）

新增 `GET /api/me`，返回当前主体的租户、主体、角色与能力清单。控制台按能力隐藏导航、面板与操作按钮。服务端授权不变。

- 能力映射只在服务端定义一处。前端不写角色名分支。
- `admin` 隐含全部能力。未知角色只得到基础能力。多角色取并集。
- 导航按钮、面板与操作按钮用 `data-capability` 声明所需能力，前端用一个通用循环处理。
- 当前标签页的能力被移除时，回退到第一个可见标签，不留下空面板。
- 隐藏是体验层，不是授权层。每个接口保留原检查与 403 语义。
- 能力清单请求失败时保持现有布局，控制台仍可用。

## 数据形状

服务端一张角色到能力的映射表，加一个纯函数 `capabilities_for(roles)`。前端只持有能力集合，不持有角色表。能力名见 `docs/contracts/console.md` 的 `GET /api/me` 一节。

能力和界面的对应：

| 界面 | 能力 |
| --- | --- |
| Chat | `chat.run` |
| Runs | `runs.read` |
| Sessions | `sessions.read` |
| Approvals 面板 / 决定按钮 | `approvals.read` / `approvals.decide` |
| Grants 面板 / 申请 / 决定 | `grants.read` / `grants.request` / `grants.decide` |
| Plans | `runs.read` |
| Registry 面板 / Open chat / Unload | `registry.read` / `registry.load` |
| Tools | `tools.read` |
| Connectors 面板 / 注册与停用 | `connectors.read` / `connectors.manage` |
| Peers 面板 / 注册、授权与撤销 | `peers.read` / `peers.manage` |
| Policy 面板 / 保存 | `policy.read` / `policy.write` |

## 新增文件

- `tests/test_console_me.py`
- `docs/evidence/SLICE-117-role-views.txt`
- `docs/evidence/ui/SLICE-117-operator.png`
- `docs/evidence/ui/SLICE-117-viewer.png`

## 修改文件

- `docs/contracts/console.md`（`GET /api/me`）
- `src/adk_agent/console.py`（能力映射、接口、`data-capability` 与前端过滤）
- `docs/specs/ROADMAP.md`
- `docs/PROGRESS.md`

## 完成判据（可执行）

- [x] `admin` 得到全部能力 -> `tests/test_console_me.py::test_admin_gets_every_capability`
- [x] `operator` 得到审批与查看能力，没有管理与写入能力 -> `::test_operator_capabilities`
- [x] `publisher` 得到发布与工具能力，没有审批决定能力 -> `::test_publisher_capabilities`
- [x] `viewer` 只有基础能力 -> `::test_viewer_gets_base_capabilities`
- [x] 未知角色只得到基础能力 -> `::test_unknown_role_falls_back_to_base`
- [x] 多角色取并集 -> `::test_multiple_roles_union`
- [x] 未认证返回 401 -> `::test_requires_token`
- [x] 返回当前主体的租户与 subject -> `::test_reports_identity`
- [x] operator 浏览器只看得到运营与构建面板，没有管理按钮 -> 浏览器证据
- [x] viewer 浏览器只看得到 Chat、Runs、Sessions -> 浏览器证据
- [x] 深链到无权标签会回退 -> 浏览器证据
- [x] 服务端 403 行为不变 -> 现有用例与全量门禁
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：没有 `/api/me`，前端只能猜角色 -> 期望 `::test_admin_gets_every_capability` 失败（404）
- [x] 反例 2：未知角色被当成 admin，能力过授 -> 期望 `::test_unknown_role_falls_back_to_base` 失败
- [x] 反例 3：viewer 仍看到 Policy 与 Connectors 标签 -> 期望浏览器证据中出现越权标签
- [x] 反例 4：深链 `#policy` 直接打开隐藏面板 -> 期望浏览器证据中 viewer 回退到 Chat
- [x] 反例 5：多角色只取第一个角色，能力丢失 -> 期望 `::test_multiple_roles_union` 失败

红态记录: 实现前 `/api/me` 返回 404，`tests/test_console_me.py` 为 7 failed, 1 passed；页面没有 `data-capability`。

## 契约（如涉及对外接口）

先合并 `docs/contracts/console.md` 的 `GET /api/me` 一节，再改实现。

## 5 问威胁建模（10 分钟）

1. **数据**：主体、租户、角色与能力名。没有凭据、没有策略内容。
2. **调用方**：浏览器控制台、OIDC 身份提供方。
3. **信任边界**：token 到 principal；服务端到浏览器。
4. **恶意输入最坏结果**：token 伪造角色（由身份提供方负责）；把界面隐藏误当授权（缓解：服务端检查不变并在契约中写明）；未知角色被过度授权（缓解：默认只有基础能力）；能力清单失败时露出多余按钮（缓解：服务端仍拦截，界面只做体验）。
5. **失败是否泄露信息**：只返回调用方自己的主体与租户，不返回其他主体，不返回策略或凭据。

## 范围外

- 站内角色分配、租户开通与用户管理。
- OIDC claim 到角色的映射调整。
- 修改任何现有接口的授权判据。
- 按角色定制首页与仪表盘。
- 平台部署状态页。

## 证据

- 红态、实现后绿、角色浏览器证据与门禁结果: `docs/evidence/SLICE-117-role-views.txt`
- operator 视图截图: `docs/evidence/ui/SLICE-117-operator.png`
- viewer 视图截图: `docs/evidence/ui/SLICE-117-viewer.png`
