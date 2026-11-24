# ADR-0043 控制台 compose 一键发布

状态: Accepted   日期: 2026-11-25   签字: Jie CAO（会话确认，见文末）

## 背景

ADR-0041 阶段 5 要把 CLI `compose` 模板做成页面向导（诉求 3）。现状：

- `POST /api/import/agent` 只发布 manifest 记录，不带工件字节，`load` 会返回 409 `artifact_missing`，
  页面新建的 Agent 不能运行。
- 可加载的工件只有 CLI `compose` 能生成与签名：模板渲染、打包、评测门禁、registry 发布、
  工件入库都在 `compose_and_publish` 里完成，私钥只从操作员的文件读取。
- 控制台目前没有任何签名能力，审计签名与凭据 KEK 都只用于各自领域。

用户在 2026-11-24 选择「页面一键发布」：允许控制台持有专用的 compose 签名密钥，在页面里完成
创建与发布；这是新的安全风险接受。2026-11-25 同意为此新增 `registry.compose` 能力并同步更新
`tests/test_console_me.py` 的能力集合断言（按硬规则单独确认）。

## 决定

### 1. 端点

新增三个端点，全部在 principal 解析后第一条语句做能力检查：

| 方法 | 路径 | 能力 | 作用 |
|---|---|---|---|
| GET | `/api/compose/templates` | `registry.publish` | 列出模板与参数（复用 `list_templates`），并报告发布是否已配置 |
| POST | `/api/compose/preview` | `registry.publish` | 用 `build_composed` 渲染 manifest 与 `agent.py`，返回预览与工件 digest |
| POST | `/api/compose` | `registry.compose` | 用控制台密钥签名、发布并入库 |

- 预览与发布共用同一份 `build_composed`，预览字节就是发布字节，避免前后端各写一份模板。
- 请求体字段：`template_id`、`name`、`version`、`tenant`、`owner?`、`description?`、
  `instruction`、`tools`、`data_classes`。非 admin 的 `tenant` 必须等于调用方租户，否则 403
  `tenant_forbidden`。
- 错误码：`compose_invalid`（400，参数或模板不合法）、`tenant_forbidden`（403）、
  `registry_not_configured`（404）、`registry_conflict`（409）、`artifact_store_unavailable`（503）、
  `registry_unavailable`（503）。不回显异常原文。
- 模板与预览不签名，未配置密钥也可用；只有 `POST /api/compose` 在未配置密钥时返回 404
  `compose_not_configured`。
- 模板仍只有 `single-llm`；名称、工具集与指令长度沿用 `build_composed` 的校验，参数用 `repr`
  嵌入生成的 `agent.py`。

### 2. 密钥

控制台新增四个启动参数，必须同时给出：

    --compose-key PATH --compose-key-id ID \
    --compose-builder-key PATH --compose-builder-key-id ID

- 只从文件读 PEM，不接受环境变量；与审计签名密钥、凭据 KEK 完全分离，不复用。
- 只给一部分参数时启动退出 2；全部缺失时 `POST /api/compose` 返回 404 `compose_not_configured`，
  其余控制台功能不受影响；密钥文件不可读或不是合法私钥时启动退出 1。
- `in_process` 工件需要 builder 签名，因此发布路径必须同时拿到发布密钥与 builder 密钥。

### 3. 权限与审计

- 新增能力 `registry.compose`，加入 `CAPABILITIES_ALL` 与 `CAPABILITIES_PUBLISHER`
  （admin + publisher）。`tests/test_console_me.py` 的期望集合同步更新（已获确认）。
- 发布写一条 `agent.compose` 审计：`template_id`、租户/Agent/版本与工件 digest；
  **不记录指令原文**，避免把业务文本写进审计链。`AuditEvent` 新增可选的 `template_id` 字段
  （默认不序列化），`audit_event.schema.json` 随 `scripts/export_contracts.py` 重新生成。
- 评测门禁沿用 `enforce_eval_gate`。

### 4. 前端

`/agents/new` 向导：模板选择 → 参数表单 → 预览（manifest 与 `agent.py`）→ 发布 → 跳到注册表。
发布按钮要求 `registry.compose`；预览与模板读取要求 `registry.publish`；未配置时显示
「控制台未启用一键发布，请使用 CLI」。不引入新依赖，不做任意源码上传。

## 切片

- SLICE-280：能力、密钥参数、三个端点、契约、后端用例（含未配置、跨租户、非法参数、
  审计不含指令、产物可被 loader 视为已签名）。
- SLICE-281：`/agents/new` 向导、路由与导航、源码检查用例、实机截图。
- SLICE-282（按需）：操作手册补充密钥托管、轮换与最小权限。

## 备选与否决

- **只用 CLI 发布**：安全但页面新建不可运行，用户明确要页面完成。否决。
- **服务端发布未签名工件**：`AgentArtifact.signature` 必填，loader 的信任检查也需要签名。否决。
- **浏览器上传任意 ZIP 由控制台签名**：等于把任意代码放进签名路径。否决；只允许模板渲染。
- **密钥放环境变量**：与控制台已有的「密钥只从文件读」约束不一致，也更容易被进程列表或镜像泄露。否决。

## 后果

- 页面可以完整创建并发布可加载的 Agent；CLI 仍是等价入口。
- 控制台成为签名路径：持有控制台主机的人可以触发平台签名的模板代码。攻击面被模板白名单、
  参数转义、指令长度上限与 `enforce_eval_gate` 限制，但控制台本身必须按高价值目标加固。
- 需要运维托管两把私钥并规划轮换；没有密钥时该功能显式关闭，不影响其他面板。

## 风险

- 模板只有 `single-llm`，仍可能被用于批量发布；发布沿用 registry 的版本冲突与配额语义，
  必要时可加二级限流。
- 预览会把生成的 `agent.py` 返回浏览器；不含密钥或宿主信息，仅为模板输出。
- 签名密钥泄露等同发布权泄露；轮换需要同时更新注册表信任集与 builder 校验集。

## 确认记录（2026-11-24 / 2026-11-25 会话确认）

1. 2026-11-24：用户选择「页面一键发布」，接受控制台持有专用 compose 签名密钥与
   `registry.compose` 能力。
2. 2026-11-25：用户同意新增 `registry.compose` 并同步更新 `tests/test_console_me.py`
   的角色能力集合断言（按硬规则单独确认）。
