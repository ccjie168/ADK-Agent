# SLICE-077 生命周期拦截、控制台与命令

状态: merged
依据: ADR-0010 第 4、5 条，SLICE-076。

## 意图（要什么，不写怎么写）

状态能读写之后，这一刀让退役真正生效，并把状态带到控制台和市场页。

- `load_registry_agents` 按引用加载前检查生命周期，退役版本报错；`console --agent-ref` 与 `serve --agent-ref` 启动失败退出 1。
- `POST /api/registry/load` 对退役版本返回 409 `version_retired`；废弃版本允许加载。
- `/api/registry` 每个条目增加 `lifecycle`，市场页对 `deprecated` 显示警告徽标，对 `retired` 禁用 Open chat 并显示原因。
- 新增 `adk-agent lifecycle set --tenant T --id ID --version V --status S [--reason TEXT]`，支持 `--registry DIR` 与 `--registry-url URL`。
- 控制台在 `--registry-url` 模式下通过 `get_lifecycle` 读取状态；文件模式用 `FileAgentLifecycleStore`。
- 不中断已加载的 agent。

## 新增文件

- `tests/test_lifecycle_enforcement.py`
- `docs/evidence/SLICE-077-lifecycle-enforcement.txt`

## 修改文件

- `src/adk_agent/registry/refs.py`、`registry/__init__.py`
- `src/adk_agent/console.py`、`src/adk_agent/cli.py`
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
load_registry_agents(..., lifecycle: AgentLifecycleStore | None = None)
  退役 -> RefError("... is retired")

RegistryEntry += "lifecycle": {"status", "changed_at", "changed_by", "reason"}

POST /api/registry/load
  退役 -> 409 {"error": "version_retired"}

lifecycle set --status published|deprecated|retired
```

## 完成判据（可执行）

- [x] 退役版本无法按引用加载 -> `tests/test_lifecycle_enforcement.py::test_ref_load_refuses_retired`
- [x] 废弃版本仍可加载 -> `::test_ref_load_allows_deprecated`
- [x] 控制台按需加载返回 409 -> `::test_console_load_refuses_retired`
- [x] 控制台列表带 lifecycle -> `::test_registry_listing_includes_lifecycle`
- [x] 文件模式命令改状态 -> `::test_cli_lifecycle_set_file`
- [x] HTTP 模式命令改状态 -> `::test_cli_lifecycle_set_http`
- [x] 非法状态退出 1 -> `::test_cli_rejects_bad_status`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：退役版本仍能按引用加载 -> 当前没有 lifecycle 参数
- [x] 反例 2：`lifecycle set` -> 当前 argparse 退出 2
- [x] 反例 3：`/api/registry` 条目没有 lifecycle -> 当前缺字段

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：生命周期状态、原因、被拦截的版本。
2. **调用方**：运维、控制台用户、启动脚本。
3. **信任边界**：状态存储到加载路径；token 到写权限。
4. **恶意输入最坏结果**：退役版本被绕过加载（缓解：按引用加载与控制台按需加载两处都检查，服务端已有状态）；非 admin 改状态（服务端 403）；原因注入到 UI（缓解：textContent）。
5. **失败是否泄露信息**：错误只报版本与状态。

## 范围外

- 中断已运行会话。
- 批量退役与定时下线。
- 回滚到旧版本。
- 工件与报告回收。

## 证据

- 反例红: `docs/evidence/SLICE-077-lifecycle-enforcement.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真服务 + 真控制台
