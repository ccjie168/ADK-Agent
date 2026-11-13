# SLICE-068 从注册表启动

状态: planned
依据: ADR-0008 第 6 条，SLICE-067，`docs/contracts/cli.md`。

## 意图（要什么，不写怎么写）

加载器已经能按引用加载，但控制台和 MCP 还只能读本地 Python 文件。这一刀把 `--agent-ref TENANT/ID@VERSION` 接进 `console`、`serve` 和 `serve-many`，注册表里发布的工件可以直接跑起来。

- 新增 `registry/refs.py`：`parse_agent_ref`、`load_registry_agents`、`RefError`。
- `--agent-ref` 可重复；与本地文件参数互斥。
- 工件来源：`--artifact-dir` 或 `ARTIFACT_URL`，必须给一个。
- 可信公钥：`--artifact-keys FILE` 或 `ADK_ARTIFACT_KEYS`，必须给一个。
- 加载流程：列出租户记录找版本，用记录摘要调 `load_agent`；重名报错。
- 不接 A2A 启动。

## 新增文件

- `src/adk_agent/registry/refs.py`
- `tests/test_registry_startup.py`
- `docs/evidence/SLICE-068-registry-startup.txt`

## 修改文件

- `src/adk_agent/registry/__init__.py`
- `src/adk_agent/cli.py`
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
parse_agent_ref("acme/bot@1.0.0") -> ("acme", "bot", "1.0.0")
  不匹配 ^<safe>/<safe>@<safe>$ -> RefError

load_registry_agents(refs, *, registry, store, trust, loader) -> dict[str, BaseAgent]
  registry.list(tenant) -> 找 id/version -> AgentRef(digest=record.digest)
  load_agent(...) -> 以 agent.name 为键；重名 -> RefError
```

## 完成判据（可执行）

- [ ] 解析引用 -> `tests/test_registry_startup.py::test_parse_agent_ref`
- [ ] 非法引用被拒 -> `tests/test_registry_startup.py::test_parse_rejects_bad_ref`
- [ ] 按引用加载出 agent -> `tests/test_registry_startup.py::test_load_registry_agents`
- [ ] 版本不存在被拒 -> `tests/test_registry_startup.py::test_unknown_version`
- [ ] 重名被拒 -> `tests/test_registry_startup.py::test_duplicate_name`
- [ ] 控制台用 `--agent-ref` 启动 -> `tests/test_registry_startup.py::test_console_loads_from_registry`
- [ ] `serve` 用 `--agent-ref` 启动 -> `tests/test_registry_startup.py::test_serve_loads_from_registry`
- [ ] 两种来源互斥 -> `tests/test_registry_startup.py::test_sources_are_exclusive`
- [ ] 缺工件来源或公钥退出 1 -> `tests/test_registry_startup.py::test_missing_artifact_config`
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.registry import parse_agent_ref` -> 当前 `ImportError`
- [ ] 反例 2：`console --agent-ref acme/bot@1.0.0` -> 当前 argparse 退出 2（参数不存在）
- [ ] 反例 3：不配 `ADK_ARTIFACT_KEYS` 仍加载 -> `test_missing_artifact_config`

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、id、version、工件、公钥。
2. **调用方**：运维和开发者启动命令。
3. **信任边界**：注册表到运行进程；工件代码执行边界同 SLICE-067。
4. **恶意输入最坏结果**：引用指向未签名版本（缓解：`load_agent` 强制工件与验签）；重名 agent 覆盖（缓解：重名报错）；未配置公钥时静默跳过验签（缓解：缺配置退出 1）。路径注入（缓解：引用三段都走注册表的路径白名单）。
5. **失败是否泄露信息**：错误只报引用或阶段，不回显公钥。

## 范围外

- A2A 从注册表启动。
- 控制面 API 与市场界面。
- Postgres 注册表。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
