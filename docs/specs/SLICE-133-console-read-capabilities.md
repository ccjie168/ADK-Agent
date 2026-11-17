# SLICE-133 控制台读接口的能力校验

状态: gated
依据: ADR-0022 第 1、8 条。控制台按能力隐藏面板与标签，但这些面板背后的读接口大多只做认证加租户过滤；任何登录主体都能直接调用，绕过界面拿到审计、策略、连接器、凭据与对端配置。本切片把服务端读路径对齐到界面已经使用的能力名。

## 意图（要什么，不写怎么写）

1. 下表每个读接口在返回数据前检查对应能力，缺少时返回 403 `{"error": "forbidden"}`。
2. 能力名只复用 ADR-0022 的现有名称，不新增能力。
3. 顺序为 `_principal_for` → 租户参数检查（若有）→ 能力检查 → 存储读取；既有租户用例的 `tenant_forbidden` 断言保持不变。
4. `GET /api/audit` 收紧后，聊天面板里的“Recent audit”区块按 `audit.read` 隐藏；运行进度不受影响。
5. `admin` 行为不变。`operator` 只在 `GET /api/tools` 上由 200 变 403，因为 Tools 标签本就按 `tools.read` 隐藏且 `operator` 没有该能力；其余读接口对 `operator` 行为不变。

| 路由 | 能力 | 界面消费方 |
| --- | --- | --- |
| `GET /api/audit` | `audit.read` | 聊天面板的 Recent audit |
| `GET /api/policy` | `policy.read` | Policy 标签 |
| `GET /api/registry` | `registry.read` | Registry 标签 |
| `GET /api/registry/{tenant}/{id}/{version}/eval` | `registry.read` | Registry 面板内评测块 |
| `GET /api/tools` | `tools.read` | Tools 标签 |
| `GET /api/tool-grants`、`/usage` | `grants.read` | Grants 标签 |
| `GET /api/connectors` | `connectors.read` | Connectors 标签 |
| `GET /api/connector-requests` | `connectors.read` | Connectors 面板内的申请区 |
| `GET /api/credentials` | `connectors.read` | Credentials 标签 |
| `GET /api/peers` | `peers.read` | Peers 标签 |
| `GET /api/remote-agents` | `peers.read` | Peers 面板内的远程目录 |

## 数据形状

- 复用 `console._capabilities_for(roles)`，不新增契约类型。
- 评测报告与凭据没有独立能力名或独立面板，分别沿用 Registry 与 Connectors 标签的门控能力。

## 契约（先改）

- `docs/contracts/console.md`：上表每个读接口写明所需能力与 403；补一节 `GET /api/policy` 的读契约。
- 说明租户参数检查先于能力检查，以及 `audit.read` 对聊天面板审计区块的影响。

## 新增/修改文件

- 修改 `src/adk_agent/console.py`
- 修改 `tests/test_console_audit.py`、`test_console_registry.py`、`test_console_tools.py`、`test_console_tool_grants.py`、`test_console_connectors.py`、`test_console_credentials.py`、`test_console_connector_requests.py`、`test_console_peers.py`、`test_console_remote_agents.py`、`test_policy_api.py`
- 文档：`docs/specs/ROADMAP.md`、`docs/PROGRESS.md`
- 证据：`docs/evidence/SLICE-133-console-read-capabilities.txt`

## 完成判据（可执行）

- [x] 无角色主体对 11 个读接口均得 403 `forbidden` -> 各测试文件的 `test_read_requires_capability`
- [x] `admin` 读行为不变；`operator` 除 `GET /api/tools` 变 403 外不变 -> 各文件既有用例与 `test_operator_lacks_tools_capability`
- [x] 发布者不能读审计、策略、连接器、凭据与对端目录；能读注册表、工具与授权 -> `test_console_tools.py` 与 `test_console_registry.py` 的新用例
- [x] 租户参数错误仍先返回 403 `tenant_forbidden` -> 既有 `test_cross_tenant_forbidden`
- [x] 聊天页在无 `audit.read` 时隐藏审计区块 -> `test_console.py` 的页面用例
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：无角色主体的 `GET /api/audit` 返回 200 -> 期望 `test_read_requires_capability` 失败
- [x] 反例 2：发布者 `GET /api/connectors` 返回 200 -> 期望 403

## 5 问威胁建模（10 分钟）

1. **数据**：审计事件（含审批与工具调用）、策略绑定、注册表条目、工具目录与授权、连接器与凭据元数据、对端与远程目录。
2. **调用方**：任何持有效 token 的控制台主体。
3. **信任边界**：前端能力清单到服务端授权。
4. **恶意输入最坏结果**：越权读取跨角色治理数据（缓解：服务端能力检查）；跨租户读取（缓解：租户检查保持原样并先执行）；界面隐藏被当成授权（缓解：服务端检查，隐藏只影响展示）。
5. **失败是否泄露信息**：403 只回 `forbidden`，不透露资源是否存在；租户参数的 `tenant_forbidden` 只暴露调用方自己的租户。

## 已知小缺口

- 各存储未配置的 404 与 `status` 非法的 400 先于能力检查；它们只暴露“该存储是否配置”与“参数是否合法”，不泄露租户或治理数据。
- `GET /api/registry` 用 `registry.read` 同时返回远端目录条目，而 `GET /api/remote-agents` 需要 `peers.read`；发布者能经注册表看到远端元数据，与 Registry 面板的可见范围一致。

## 范围外

- 写接口的能力对齐（连接器、凭据、对端、注册表 load/unload 仍按 admin 或既有 RBAC 判定）。
- 站内角色分配与租户开通。
- 运行、计划、会话、trace 等基础能力接口，所有登录主体都有对应基础能力。
- 审批接口已由 SLICE-132 收口。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-133-console-read-capabilities.txt`
