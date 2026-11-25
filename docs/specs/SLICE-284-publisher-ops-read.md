# SLICE-284 publisher 角色获得 `ops.read`

状态: gated
依据: PROGRESS 第 16 条既有缺口（`publisher` 没有 `ops.read`，总览对其不可见）；
用户 2026-11-25 会话确认新增并同步修改 `tests/test_console_me.py` 的 PUBLISHER 期望集合

## 意图

`publisher`/`developer` 登录后看不到总览首页（`/api/overview` 与 `/` 面板都要求 `ops.read`），
因为它们的角色集合里没有 `ops.read`。发布者需要看到平台概览才能判断发布后的加载与运行情况。

本切片把 `ops.read` 加进 `CAPABILITIES_PUBLISHER`（`developer` 复用同一集合）：

- `publisher` 获得总览、配额、RAG、语义等 `ops.read` 读面板的可见性；
- `operator`、`admin`、`base` 的能力不变，能力词汇表（`CAPABILITIES_ALL`）不变；
- `tests/test_console_me.py` 的 PUBLISHER 字面量与新增回归用例同步更新（已获用户同意）。

这不扩大写能力：`publisher` 仍没有审批、连接器管理、策略写入或成员管理。

## 契约（先改）

- `docs/contracts/console.md`：内置角色一节把 `ops.read` 加进 `publisher`/`developer` 的能力列表。

## 完成判据

- [ ] publisher 的 `/api/me` 含 `ops.read` -> `test_publisher_capability_set_includes_ops_read`
- [ ] publisher 可读 `/api/overview` -> `test_publisher_gets_the_overview`
- [ ] base 角色仍被 `ops.read` 拒绝 -> `test_base_role_still_lacks_the_overview`
- [ ] `tests/test_console_me.py` 的 PUBLISHER 集合与角色表一致（含 `ops.read`）
- [ ] `--full` 门禁通过

## 反例

实现前，publisher 的 `/api/me` 不含 `ops.read`，`/api/overview` 返回 403；上述两条新用例失败。
base 角色用例在旧代码上通过，作为不扩大基础能力的回归保护。

## 5 问威胁建模

1. **数据**：平台聚合计数（待审批数、注册 Agent 数、工具数、待处理授权数）；不含事件或凭据内容。
2. **调用方**：`publisher`/`developer` 获得只读可见性；写接口与 `ops.status` 不在授予范围。
3. **信任边界**：聚合卡按各子能力（`approvals.read`、`registry.read`、`tools.read`、`grants.read`）
   分别取数，publisher 已有的读能力决定卡片是否有值，其余为 `null`。
4. **恶意输入**：无请求体；租户过滤沿用现有逻辑（非 admin 只用调用方租户）。
5. **失败是否泄露信息**：卡片取数失败保留 `null`，日志只记租户；接口不返回异常文本。

## 范围外

- 深色主题与命令面板（视觉项）。
- 同一时间戳事件的跨后端顺序（契约项）。
- 自定义角色库的默认种子回填由 `_seed_role_store` 负责，无需迁移。

## 证据

- `docs/evidence/SLICE-284-publisher-ops-read.txt`
