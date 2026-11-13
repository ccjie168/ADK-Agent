# SLICE-081 工具授权申请、审批与控制台

状态: merged
依据: ADR-0011 第 4 条，SLICE-078，SLICE-080。

## 意图（要什么，不写怎么写）

运行时已经能用临时授权，但只能手工写存储。这一刀补上申请、审批入口，让 ADR-0011 闭环。

- 控制台三个接口：列表、申请、审批；申请校验版本存在、digest 一致、未退役；审批只给 admin。
- 申请与决定写审计（`tool_grant.request`、`tool_grant.decide`）。
- 前端新增 Grants 面板：列表、用选中的注册表版本发起申请、审批按钮。
- CLI 新增 `tool-grants list|request|decide`，文件目录与 `GRANT_URL` 都可。
- `expires_hours` 默认 24、上限 168；空原因拒绝。

## 新增文件

- `tests/test_console_tool_grants.py`
- `tests/test_cli_tool_grants.py`
- `docs/evidence/SLICE-081-tool-grant-console.txt`

## 修改文件

- `src/adk_agent/console.py`、`src/adk_agent/cli.py`
- `docs/contracts/console.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GET  /api/tool-grants?tenant=&status= -> [ToolGrantRequest]
POST /api/tool-grants {tenant?, agent_id, version, digest, tool_id,
                       data_classes?, reason, expires_hours?} -> 201
POST /api/tool-grants/{id}/decide {approved, reason} -> 200

tool-grants list --tenant T [--status S]
tool-grants request --tenant T --id ID --version V --digest D --tool TOOL --reason TEXT [--expires-hours N]
tool-grants decide ID (--approve | --deny) [--reason TEXT]
```

## 完成判据（可执行）

- [x] 申请后出现在列表 -> `tests/test_console_tool_grants.py::test_request_and_list`
- [x] 版本不存在 404 -> `::test_request_requires_published_version`
- [x] 退役版本 409 -> `::test_retired_version_rejected`
- [x] 跨租户 403 -> `::test_cross_tenant_forbidden`
- [x] 非 admin 审批 403 -> `::test_non_admin_cannot_decide`
- [x] 审批成功并写审计 -> `::test_decide_and_audit`
- [x] 终态与过期分别 409/410 -> `::test_decide_terminal_and_expired`
- [x] 未配置存储 404 -> `::test_no_store`
- [x] CLI 列表/申请/审批 -> `tests/test_cli_tool_grants.py::test_cli_file_flow`
- [x] CLI 非法小时退出 1 -> `::test_cli_rejects_bad_hours`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`GET /api/tool-grants` -> 当前 404
- [x] 反例 2：`tool-grants` 命令 -> 当前 argparse 退出 2
- [x] 反例 3：退役版本仍能申请 -> 当前无此接口

## 契约（如涉及对外接口）

已先改 `docs/contracts/console.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：申请锚点、原因、申请人、审批人、有效期。
2. **调用方**：控制台用户、运维。
3. **信任边界**：HTTP 到授权存储；角色到审批权。
4. **恶意输入最坏结果**：为任意 digest 申请（缓解：版本与 digest 必须匹配已发布记录）；非 admin 自批（缓解：403）；超大有效期（缓解：上限 168 小时）；退役版本重新放行（缓解：409）。
5. **失败是否泄露信息**：错误码固定；列表只返回授权租户。

## 范围外

- 撤回接口（存储支持，控制台暂不暴露）。
- 自动续期与到期提醒。
- 授权统计。
- 数据分级强制执行。

## 证据

- 反例红: `docs/evidence/SLICE-081-tool-grant-console.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真控制台 + 截图
