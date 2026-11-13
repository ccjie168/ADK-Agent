# SLICE-078 工具授权请求类型与存储

状态: merged
依据: ADR-0011 第 1 至 4 条。

## 意图（要什么，不写怎么写）

先把临时授权的领域类型和存储做出来。运行时合并、控制台接口与命令留给 SLICE-079 和 080。

- `core/tool_grants.py`：`ToolGrantRequest`、`GrantStatus`、`effective_status`、`is_active`，以及存储错误类型。
- `ToolGrantStore` 端口：申请、读取、列表、审批、撤回、按版本查有效授权。
- 文件实现供单机开发，Postgres 实现供多副本；过期在读取时判断，不跑后台任务。
- 待审与已批准都带 `expires_at`；终态不可变；重复申请同 id 同内容幂等。

## 新增文件

- `src/adk_agent/core/tool_grants.py`
- `src/adk_agent/registry/tool_grants.py`
- `src/adk_agent/registry/tool_grants_postgres.py`
- `tests/core/test_tool_grants.py`
- `tests/registry/test_tool_grant_store.py`
- `docs/evidence/SLICE-078-tool-grant-store.txt`

## 修改文件

- `src/adk_agent/core/__init__.py`、`core/ports.py`
- `src/adk_agent/registry/__init__.py`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
GrantStatus = pending | approved | denied | expired | cancelled

ToolGrantRequest {
  request_id, tenant, agent_id, version, digest, tool_id,
  data_classes, reason, status,
  requested_by, requested_at, expires_at,
  decided_by?, decided_at?, decision_reason
}

ToolGrantStore:
  add(request) -> request
  get(id) -> request | null
  list(tenant, status=None) -> [request]
  decide(id, approved, decided_by, reason) -> request
  cancel(id, by, reason) -> request
  active(tenant, agent_id, version, digest, tool_id) -> bool

effective_status: pending/approved 且 now >= expires_at -> expired
```

## 完成判据（可执行）

- [x] 模型拒绝 naive 时间与倒置有效期 -> `tests/core/test_tool_grants.py::test_request_validation`
- [x] 过期映射 -> `::test_effective_status`
- [x] 文件申请幂等与冲突 -> `tests/registry/test_tool_grant_store.py::test_file_add_idempotent`
- [x] 文件审批与终态 -> `::test_file_decide`
- [x] 过期请求不能审批 -> `::test_file_expired_decide`
- [x] 撤回只对 pending 生效 -> `::test_file_cancel`
- [x] 有效授权按版本与 digest 命中 -> `::test_file_active`
- [x] Postgres 同套语义 -> `::test_postgres_lifecycle`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import ToolGrantRequest` -> 当前 `ImportError`
- [x] 反例 2：文件存储不存在 -> 当前 `ImportError`
- [x] 反例 3：过期审批被接受 -> 当前无此行为，实现后由用例守住

## 契约（如涉及对外接口）

不涉及。控制台接口在 SLICE-080 先改 `docs/contracts/console.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：版本锚、工具 id、申请人、审批人、原因、有效期。
2. **调用方**：运行时守卫、控制台、CLI。
3. **信任边界**：审批存储到运行时放行；版本 digest 到授权范围。
4. **恶意输入最坏结果**：跨版本继承授权（缓解：按 digest 查询）；过期授权继续生效（缓解：读取时判断）；撤回后仍放行（缓解：终态与状态过滤）；篡改请求文件（缓解：文件实现仅开发、Postgres 为主）。
5. **失败是否泄露信息**：错误只报请求 id 与状态。

## 范围外

- 运行时合并与配置（SLICE-079）。
- 控制台接口、CLI 与审计（SLICE-080）。
- 数据分级强制执行、自动续期、回收扫描。

## 证据

- 反例红: `docs/evidence/SLICE-078-tool-grant-store.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres
