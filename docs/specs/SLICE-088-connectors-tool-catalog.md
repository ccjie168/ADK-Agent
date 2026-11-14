# SLICE-088 连接器并入工具目录

状态: merged
依据: ADR-0013 第 4 条，SLICE-075 只读工具目录。

## 意图（要什么，不写怎么写）

连接器能注册、能执行、能授权，但工具目录仍是静态文件。运营看不到连接器来源的工具，也看不到哪些已发布版本被授权使用它们。这一刀把已启用的连接器并入 `GET /api/tools` 视图。

- `tools/catalog.py` 新增纯函数，把 `ConnectorSpec` 转成 `ToolEntry`。
- 控制台在静态目录基础上合并连接器条目，同一 `tool_id` 时静态条目优先。
- 只配置连接器存储、没有静态目录时，接口仍返回连接器条目。
- 只纳入已启用的连接器，与 `build_connector_tools` 的暴露范围一致。
- 授权关系复用现有按 `tool_id` 聚合注册表 `manifest.tool_grants` 的逻辑。

## 新增文件

- `docs/evidence/SLICE-088-connectors-tool-catalog.txt`
- `docs/specs/SLICE-088-connectors-tool-catalog.md`

## 修改文件

- `src/adk_agent/tools/catalog.py`（连接器到 `ToolEntry` 的转换）
- `src/adk_agent/tools/__init__.py`（导出）
- `src/adk_agent/console.py`（`GET /api/tools` 合并与 503）
- `tests/test_tool_catalog.py`、`tests/test_console_tools.py`
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
connector_tool_entries(specs: Iterable[ConnectorSpec]) -> list[ToolEntry]
  ToolEntry{
    tool_id: spec.connector_id,
    description: f"{spec.kind} connector to {spec.base_url}",
    source: "connector",
    data_classes: spec.data_classes,
    requires_approval: false,
    tenant: spec.tenant
  }
  只转换 spec.enabled 为真的连接器。

GET /api/tools?tenant=T -> [ToolEntry + granted_agents]
  静态目录条目与连接器条目合并，按 tool_id 去重（静态优先），按 tool_id 排序。
```

## 完成判据（可执行）

- [x] 启用连接器转成条目 -> `tests/test_tool_catalog.py::test_connector_entry`
- [x] 停用连接器被跳过 -> `::test_connector_entry_skips_disabled`
- [x] 全局与租户连接器都进视图 -> `tests/test_console_tools.py::test_connector_tools_merged`
- [x] 同 id 静态条目优先 -> `::test_static_entry_wins_over_connector`
- [x] 只有连接器时也能返回 -> `::test_connectors_without_catalog`
- [x] 两者都没配置返回 404 -> `::test_no_catalog`
- [x] 连接器存储不可达返回 503 -> `::test_connector_store_unavailable`
- [x] 连接器工具 id 能关联注册表授权 -> `::test_connector_grants_from_registry`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools import connector_tool_entries` -> 当前 `ImportError`
- [x] 反例 2：只配连接器存储、不配 `--tool-catalog` 时 `GET /api/tools` -> 当前 404
- [x] 反例 3：静态目录与连接器同 id 时返回静态条目 -> 当前连接器条目根本不出现

## 契约（如涉及对外接口）

已先改 `docs/contracts/console.md` 的 `GET /api/tools` 段。

## 5 问威胁建模（10 分钟）

1. **数据**：连接器 id、类型、基础 URL、数据分级、租户、注册表授权关系。
2. **调用方**：浏览器控制台用户、运维。
3. **信任边界**：连接器存储到目录视图；注册表记录到授权视图。
4. **恶意输入最坏结果**：跨租户看到别家连接器（缓解：沿用 `connectors.list(target)` 可见性与 403）；把未授权连接器显示成已授权（缓解：仍只按 `manifest.tool_grants` 聚合）；连接器描述注入标记（缓解：前端 `textContent` 渲染，纯文本）。
5. **失败是否泄露信息**：只回固定错误码，不回显存储 DSN 或连接器凭据引用。

## 范围外

- 一个连接器暴露多个工具 id。
- 连接器健康检查与可达性探测。
- 在目录里增删授权或发起申请。
- 把连接器条目写回静态目录文件。

## 证据

- 反例红：`docs/evidence/SLICE-088-connectors-tool-catalog.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 实机：同文件 live 段，真 Postgres 控制面与回环控制台的 `/api/tools`
