# SLICE-288 侧栏入口按能力过滤

状态: gated
依据: SLICE-284 证据记录的新观察（侧栏入口不按能力隐藏，点进去才 403）

## 意图

侧栏是硬编码的 26 个入口，不按主体的能力隐藏：publisher 能看到「审批」「审计」「角色」等入口，
点进去才被视图或接口 403。保留现有入口标记（既有测试按 `to="/..."` 断言导航，不改旧断言），
给每个入口加 `v-if="auth.hasCapability('...')"`；分组按组内任一能力加组级 `v-if`，
全组无权限时整组隐藏。

映射（与各视图的 `denied` 条件一致）：

| 入口 | 能力 |
|---|---|
| 总览、安全、语义层、检索、配额 | `ops.read` |
| Agent、注册表 | `registry.read` |
| 运行、计划、Ask AI、导入 | `runs.read` |
| 会话 | `sessions.read` |
| 审批 | `approvals.read` |
| 聊天 | `chat.run` |
| 审计 | `audit.read` |
| 策略 | `policy.read` |
| 角色、用户 | `roles.read` |
| 工具 | `tools.read` |
| 授权 | `grants.read` |
| 连接器、凭据 | `connectors.read` |
| 对端 | `peers.read` |
| 新建 Agent | `registry.publish` 或 `registry.compose`（进入后由视图说明 compose-only 不可发布） |
| 模型 | `model.read` |
| 生态 | `tools.read`、`connectors.read`、`peers.read` 任一 |
| 设置 | 无（对所有登录主体可见） |

只改前端导航；服务端授权不变，深链接仍由各接口拒绝。

## 契约（先改）

无后端接口变化；`docs/contracts/console.md` 的前端壳一节补一句「侧栏入口按能力过滤」。

## 完成判据

- [ ] 每个入口都带能力门控 -> `test_nav_gates_every_entry`
- [ ] 除设置外没有无门控入口 -> `test_nav_has_no_ungated_entries`
- [ ] 组条件覆盖组内全部子能力（无入口时整组隐藏） -> `test_nav_groups_cover_every_child_capability`
- [ ] 生态入口接受三个读取能力之一 -> `test_ecosystem_needs_any_of_its_three_sources`
- [ ] 向导入口接受 publish 或 compose -> `test_wizard_entry_accepts_publish_or_compose`
- [ ] `web/dist/` 重建，实机截图确认 publisher 看不到审计/审批 -> 证据
- [ ] `--full` 门禁通过

## 反例

实现前 `App.vue` 没有任何能力门控，四条用例在 master 的 `App.vue` 上全部失败
（证据里记录了用 master 版本替换后的红灯输出）。

## 5 问威胁建模

1. **数据**：主体能力清单（`/api/me`），只是名称。
2. **调用方**：所有登录主体；导航不参与授权，只影响可见性。
3. **信任边界**：前端过滤可被绕过（直接改 hash），服务端 403 仍是唯一判据。
4. **恶意输入**：无新输入；能力名来自服务端。
5. **失败是否泄露信息**：隐藏入口不削弱接口鉴权；`/api/me` 失败时能力为空，只显示无能力入口。

## 范围外

- 服务端授权变化。
- 移动端抽屉交互（沿用既有实现）。

## 证据

- `docs/evidence/SLICE-288-nav-capabilities.txt`
- `docs/evidence/ui/SLICE-288-publisher-nav.png`
