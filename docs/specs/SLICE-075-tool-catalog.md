# SLICE-075 只读工具目录（UI-4）

状态: merged
依据: `docs/contracts/console.md`、`docs/contracts/cli.md`，方向评审 Phase C。

## 意图（要什么，不写怎么写）

工具网关有授权、审计和守卫，但平台上看不到“有哪些工具、谁被授权用了”。这一刀做只读工具目录：控制台读一份工具清单，叠加注册表里各 agent 的 `tool_grants`，展示工具来源、数据分级、是否需要审批和被哪些版本引用。

- 新增 `tools/catalog.py`：`ToolEntry`、`ToolCatalog`、`load_tool_catalog`、`ToolCatalogError`。
- 控制台新增 `--tool-catalog FILE` 与 `GET /api/tools?tenant=`。
- 目录条目可全局或按租户；非 admin 只能看自己的租户。
- `granted_agents` 从目标租户的注册表记录里按 `tool_id` 聚合，按 `(id, version)` 排序。
- 前端新增 Tools 面板，复用 Registry 的租户下拉。
- 不做申请、授权变更、调用统计。这些留给后续切片。

## 新增文件

- `src/adk_agent/tools/catalog.py`
- `tests/test_tool_catalog.py`
- `tests/test_console_tools.py`
- `docs/evidence/SLICE-075-tool-catalog.txt`

## 修改文件

- `src/adk_agent/console.py`：目录参数、端点、Tools 面板
- `src/adk_agent/cli.py`：`--tool-catalog`
- `src/adk_agent/tools/__init__.py`
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ToolCatalog {version: 1, tools: [ToolEntry]}
ToolEntry {
  tool_id: str (^[A-Za-z0-9][A-Za-z0-9._+-]*$),
  description: str = "",
  source: "function" | "openapi" | "mcp" | "connector",
  data_classes: list[str] = [],
  requires_approval: bool = false,
  tenant: str | null = null
}

GET /api/tools?tenant=acme -> [ToolEntry + granted_agents: [{id, version}]]
```

## 完成判据（可执行）

- [x] 合法目录加载 -> `tests/test_tool_catalog.py::test_load_catalog`
- [x] 重复 id 被拒 -> `::test_duplicate_tool_id`
- [x] 非法来源被拒 -> `::test_bad_source`
- [x] 非法版本被拒 -> `::test_bad_version`
- [x] 全局与租户条目筛选 -> `tests/test_console_tools.py::test_lists_global_and_tenant_tools`
- [x] 授权来自注册表 -> `::test_grants_from_registry`
- [x] 非 admin 跨租户 403 -> `::test_cross_tenant_forbidden`
- [x] 未配置目录 404 -> `::test_no_catalog`
- [x] 无注册表时授权为空 -> `::test_grants_empty_without_registry`
- [x] CLI 接线并拒绝坏文件 -> `::test_cli_loads_catalog`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.tools import ToolCatalog` -> 当前 `ImportError`
- [x] 反例 2：`GET /api/tools` -> 当前 404
- [x] 反例 3：`console --tool-catalog FILE` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

已先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：工具 id、描述、来源、数据分级、审批标记、agent 授权关系。
2. **调用方**：浏览器控制台用户、运维。
3. **信任边界**：目录文件到控制台；注册表记录到授权视图。
4. **恶意输入最坏结果**：目录文件注入脚本（缓解：只作为纯文本渲染，`textContent`）；跨租户看到别家工具与授权（缓解：租户过滤与 403）；把未授权工具显示成已授权（缓解：只按 manifest 的 `tool_grants` 展示，不做推断）。
5. **失败是否泄露信息**：错误码固定；不返回文件路径。

## 范围外

- 工具申请与审批流。
- 授权变更写入。
- 调用次数、拒绝次数与延迟统计。
- 从工具网关或 MCP 自动发现工具。

## 证据

- 反例红: `docs/evidence/SLICE-075-tool-catalog.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真控制台 + 真目录文件
