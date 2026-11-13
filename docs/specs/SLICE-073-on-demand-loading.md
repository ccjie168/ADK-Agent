# SLICE-073 市场页按需加载版本（UI-4）

状态: merged
依据: ADR-0008 第 6 条，ADR-0009，SLICE-069，`docs/contracts/console.md`。

## 意图（要什么，不写怎么写）

市场页的 Open chat 只对启动时已加载的 agent 生效。这一刀让控制台按需从注册表加载用户选中的版本，并把它加进聊天目标。

- 新增 `POST /api/registry/load`，请求体 `{"tenant","id","version"}`。
- 加载前强制工件存在、签名可信；执行仍在控制台进程内，不是沙箱。
- 同名 agent 已在控制台加载时返回 200、`loaded=false`，不切换版本；按需加载过另一版本时返回 409 `name_conflict`。
- 已加载数量上限 `--max-loaded-agents`，默认 20。
- 控制台接工件存储与加载器：`--artifact-dir` 或 `ARTIFACT_URL`，与 `--agent-ref` 共用。
- 每次成功加载写 `agent.load` 审计。
- 前端 Open chat 先调加载接口，成功后刷新 agent 下拉并切到聊天页。

## 新增文件

- `tests/test_console_on_demand.py`
- `docs/evidence/SLICE-073-on-demand-loading.txt`

## 修改文件

- `src/adk_agent/console.py`：加载端点、运行时注册、前端按钮
- `src/adk_agent/cli.py`：`--max-loaded-agents` 与存储/加载器接线
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
POST /api/registry/load
  {"tenant": "acme", "id": "bot", "version": "1.0.0"}
  -> 200 {"name": "bot", "version": "1.0.0", "loaded": true | false}
  -> 400 invalid_request | 403 tenant_forbidden | 404 not_found | 404 registry_not_configured
  -> 409 artifact_missing | artifact_untrusted | name_conflict | load_limit
  -> 500 load_failed | 503 artifact_store_unavailable | artifact_trust_unavailable

控制台状态：
  agents: name -> BaseAgent        （启动时加载 + 按需加载）
  runtimes: name -> AgentRuntime   （同一份）
  loaded_versions: name -> version （只记录按需加载的版本）
```

## 完成判据（可执行）

- [x] 加载后出现在 `/api/agents` -> `tests/test_console_on_demand.py::test_load_adds_agent`
- [x] 加载后成为聊天目标 -> `::test_loaded_agent_has_runtime`
- [x] 启动时已加载的名字返回 loaded=false -> `::test_already_loaded_returns_false`
- [x] 版本缺失 404 -> `::test_missing_version`
- [x] 没有工件 409 -> `::test_missing_artifact`
- [x] 不可信工件 409 -> `::test_untrusted_artifact`
- [x] 跨租户 403 -> `::test_cross_tenant_forbidden`
- [x] 超过上限 409 -> `::test_load_limit`
- [x] 缺存储或公钥 503 -> `::test_requires_store_and_trust`
- [x] 同名另一版本 409 -> `::test_name_conflict_across_versions`
- [x] 坏工件 500 -> `::test_load_failure`
- [x] 成功加载写审计 -> `::test_audit_records_load`
- [x] 控制器 CLI 接线 -> `::test_cli_wires_store_and_limit`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`POST /api/registry/load` -> 当前 404/405
- [x] 反例 2：`build_console_app(..., artifact_store=...)` -> 当前 `TypeError`
- [x] 反例 3：`console --max-loaded-agents` -> 当前 argparse 退出 2

## 契约（如涉及对外接口）

先改 `docs/contracts/console.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、版本、工件代码、可信公钥。
2. **调用方**：控制台浏览器用户。
3. **信任边界**：注册表记录到进程内执行；工件存储到加载器。
4. **恶意输入最坏结果**：未签名或不可信代码被执行（缓解：加载前强制验签，未配置公钥直接拒绝）；跨租户加载（缓解：principal 租户绑定）；无限加载耗尽内存（缓解：`--max-loaded-agents`）；同名覆盖正在使用的 agent（缓解：同名不重载，版本冲突报 409）；加载失败留下半初始化状态（缓解：先构建 runner 与运行时，全部成功后再写入字典）。
5. **失败是否泄露信息**：错误码固定，不回显存储路径与密钥。

## 范围外

- 热切换同一 agent 的版本。
- 卸载已加载的 agent。
- 跨进程共享已加载集合。
- 沙箱执行（加载器仍为进程内执行）。
- 评测报告集中存储。

## 证据

- 反例红: `docs/evidence/SLICE-073-on-demand-loading.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真服务 + 真控制台 + HTTP 加载
