# SLICE-094 市场页合并远端条目

状态: merged
依据: ADR-0015 第 3 条与切片段。

## 意图（要什么，不写怎么写）

SLICE-093 有了远端目录记录，但表里看不到。这一刀把远端条目并进市场视图，加来源与信任标记，并给运营一个刷新入口。

- `GET /api/registry` 同时返回本地版本与远端条目，每条带 `source`。
- 远端条目带 `trust` 块，`pinned`、`changed`、`unreachable` 与停用状态都能被界面区分。
- 注册表与远端目录都未配置才返回 404；只配一个就只返回该来源。
- 注册表面板加来源列、信任徽标与刷新按钮；远端行不能 Open chat。
- 不改远端记录的写入路径，不可加载、不可对话。

## 新增文件

- `docs/evidence/SLICE-094-marketplace-remote.txt`
- `docs/specs/SLICE-094-marketplace-remote.md`

## 修改文件

- `src/adk_agent/console.py`（`list_registry` 合并、注册表面板）
- `tests/test_console_registry.py`
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GET /api/registry?tenant=T -> [RegistryEntry]

本地条目增加 source="local"，其余字段不变。
远端条目：
{
  tenant, id, source="remote", peer_id, label, agent_card_url, enabled,
  trust: {status, card_digest, observed_digest, checked_at}
}

排序：按 id；同 id 时 local 在前；本地同 id 按 version。
过滤：两种来源都按目标租户过滤。
```

## 完成判据（可执行）

- [x] 本地条目带 `source="local"` -> `tests/test_console_registry.py::test_entries_carry_source`
- [x] 远端条目合并并带 trust -> `::test_remote_entries_merged`
- [x] 同 id 时本地在前 -> `::test_local_sorts_before_remote`
- [x] 只有远端时也返回 200 -> `::test_remote_only`
- [x] 两者都没有返回 404 -> `::test_no_sources`
- [x] 远端条目按租户过滤 -> `::test_remote_tenant_filter`
- [x] 停用与变化状态仍返回 -> `::test_remote_states_visible`
- [x] 远端存储失败返回 503 -> `::test_remote_store_unavailable`
- [x] 面板含来源列与刷新控件 -> `::test_panel_has_remote_controls`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：只配远端目录、不配注册表时 `GET /api/registry` -> 当前 404
- [x] 反例 2：本地条目返回体里没有 `source` 键 -> 当前确认缺失
- [x] 反例 3：已登记远端记录不出现在 `GET /api/registry` -> 当前确认缺失

## 契约（如涉及对外接口）

已先改 `docs/contracts/console.md` 的 `GET /api/registry` 段。

## 5 问威胁建模（10 分钟）

1. **数据**：本地版本与远端记录的合并视图、信任状态。
2. **调用方**：控制台用户。
3. **信任边界**：远端存储到市场视图；信任状态到操作判断。
4. **恶意输入最坏结果**：把 `changed` 或 `unreachable` 显示成可信（缓解：徽标按 `trust.status` 原样渲染，文本用 `textContent`）；跨租户看到远端记录（缓解：按目标租户过滤）；把远端条目当成可加载版本（缓解：Open chat 对 `source="remote"` 禁用，服务端加载接口仍只认本地版本）。
5. **失败是否泄露信息**：错误只回固定码；不返回 card 响应体或凭据。

## 范围外

- 远端 agent 的加载与对话。
- 市场页的远端条目注册表单（已有 Peer/远程目录接口）。
- 定时刷新。

## 证据

- 反例红：`docs/evidence/SLICE-094-marketplace-remote.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，控制台同时连本地注册表与远端目录，浏览器接口返回合并后的两种条目
