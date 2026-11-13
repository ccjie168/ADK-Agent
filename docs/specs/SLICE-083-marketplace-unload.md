# SLICE-083 市场页卸载与同位置换

状态: merged
依据: SLICE-073，`docs/contracts/console.md`。

## 意图（要什么，不写怎么写）

按需加载的版本只能越积越多，选错版本后没法撤回，也无法在同一位置换成另一个版本。这一刀补卸载与置换。

- 新增 `POST /api/registry/unload`：只卸载按需加载的 agent；启动时加载的拒绝。
- 记录按需加载的租户，非 admin 不能卸载其他租户的版本。
- 卸载写 `agent.unload` 审计。
- 前端详情区加 Unload 按钮；Open chat 遇到 `name_conflict` 时自动卸载后重试一次，实现版本置换。
- 正在运行的调用不中断；卸载只影响后续加载与聊天目标。

## 新增文件

- `tests/test_console_unload.py`
- `docs/evidence/SLICE-083-marketplace-unload.txt`

## 修改文件

- `src/adk_agent/console.py`
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
POST /api/registry/unload {"name": "bot"}
  -> 200 {"name": "bot", "unloaded": true}
  -> 403 tenant_forbidden | 404 not_found | 409 not_unloadable

loaded_tenants: name -> tenant  （只记录按需加载）
```

## 完成判据（可执行）

- [x] 卸载按需 agent -> `tests/test_console_unload.py::test_unload_on_demand`
- [x] 启动 agent 拒绝 -> `::test_startup_agent_not_unloadable`
- [x] 未知 agent 404 -> `::test_unknown_agent`
- [x] 跨租户 403 -> `::test_cross_tenant_forbidden`
- [x] 卸载写审计 -> `::test_audit_records_unload`
- [x] 卸载后可换成另一版本 -> `::test_swap_after_unload`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`POST /api/registry/unload` -> 当前 404
- [x] 反例 2：同一 agent 换版本 -> 当前 409 name_conflict，无法置换

## 契约（如涉及对外接口）

已先改 `docs/contracts/console.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：agent 名、加载来源、租户、卸载事件。
2. **调用方**：控制台用户。
3. **信任边界**：HTTP 到进程内运行时注册表。
4. **恶意输入最坏结果**：卸载别人租户的 agent（缓解：租户记录与 403）；卸载启动 agent 导致基础功能消失（缓解：409）；卸载正在运行的实例造成状态丢失（缓解：运行持有引用，只改注册表）。
5. **失败是否泄露信息**：错误码固定。

## 范围外

- 批量卸载。
- 定时回收空闲 agent。
- 运行中会话迁移。

## 证据

- 反例红: `docs/evidence/SLICE-083-marketplace-unload.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真控制台
