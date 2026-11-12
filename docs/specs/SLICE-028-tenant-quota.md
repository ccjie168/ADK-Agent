# SLICE-028 租户隔离与配额（M4-1）

状态: gated
依据: ADR-0002 第 3、5、6 条

## 意图（要什么，不写怎么写）

补齐 M4 出口的第一条。

- manifest 带 `tenant`，注册表按租户分目录存储。
- 注册表查询必须带租户。跨租户查询返回 `None`，不泄露存在性。
- 注册表路径的每一段都校验，`../` 之类的值被拒绝。
- CLI 的 `new` 支持 `--tenant`，`validate` / `publish` 输出带租户。
- 运行时有配额：每租户窗口内运行次数和并发数。
- 配额是端口，内存实现先落地。超额 fail closed 并写审计。
- 计划和单次 agent 运行都受配额约束。
- 这一刀不接 OIDC，也不做配额持久化。

## 新增文件

- `src/adk_agent/core/quota.py`
- `src/adk_agent/runtime/quota.py`
- `tests/runtime/test_quota.py`
- `tests/orchestration/test_quota_gate.py`
- `docs/evidence/SLICE-028-tenant-quota.txt`

## 修改文件

- `src/adk_agent/core/manifest.py`：`AgentManifest.tenant`
- `src/adk_agent/core/ports.py`：`AgentRegistry.get(ref, tenant)`、`QuotaManager`
- `src/adk_agent/core/__init__.py`：导出配额类型
- `src/adk_agent/registry/file.py`：`<root>/<tenant>/<id>/<version>.json`
- `src/adk_agent/templates/builtin.py`：模板写入租户
- `src/adk_agent/cli.py`：`new --tenant`，输出带租户
- `src/adk_agent/runtime/execution.py`：运行时配额
- `src/adk_agent/runtime/__init__.py`：导出内存配额
- `src/adk_agent/orchestration/executor.py`：计划级配额
- `src/adk_agent/orchestration/errors.py`：`QuotaExceeded` 错误码映射
- `docs/contracts/manifest.schema.json`：重新生成
- `docs/contracts/cli.md`：租户输出和存储布局
- `tests/registry/test_file_registry.py`、`tests/test_registry_cli.py`
- `tests/templates/test_builtin.py`、`tests/test_new_cli.py`、`tests/core/test_contracts.py`
- `docs/specs/ROADMAP.md`：M4 进行中

## 完成判据（可执行）

- [x] manifest 必须有 `tenant` -> `tests/core/test_contracts.py::test_manifest_required`
- [x] 默认模板租户是 `local`，可指定 -> `tests/templates/test_builtin.py::test_rendered_manifest_uses_requested_tenant`
- [x] 注册表按租户存储 -> `tests/registry/test_file_registry.py::test_publish_is_idempotent`
- [x] 跨租户查询返回 `None` -> `tests/registry/test_file_registry.py::test_get_from_other_tenant_returns_none`
- [x] `new --tenant` 写入 manifest -> `tests/test_new_cli.py::test_new_uses_requested_tenant`
- [x] 非法租户被拒绝 -> `tests/test_new_cli.py::test_new_rejects_unsafe_tenant`
- [x] 窗口内运行次数超额 -> `tests/runtime/test_quota.py::test_run_limit_exceeded`
- [x] 窗口过期后恢复 -> `tests/runtime/test_quota.py::test_window_expiry_frees_slots`
- [x] 并发超额 -> `tests/runtime/test_quota.py::test_concurrency_limit_exceeded`
- [x] 租户互不影响 -> `tests/runtime/test_quota.py::test_tenants_have_separate_quotas`
- [x] 运行异常也释放并发槽 -> `tests/runtime/test_quota.py::test_release_on_error`
- [x] `AgentRuntime` 超额拒绝并审计 -> `tests/runtime/test_quota.py::test_runtime_denies_over_quota`
- [x] 计划超额拒绝并审计 -> `tests/orchestration/test_quota_gate.py::test_plan_denied_over_quota`
- [x] 策略至少有一个限额 -> `tests/runtime/test_quota.py::test_policy_requires_a_limit`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.runtime.quota import InMemoryQuotaManager` -> 当前 `ImportError`
- [x] 反例 2：`AgentManifest` 不带 `tenant` -> 当前通过，期望 `ValidationError`
- [x] 反例 3：租户 A 的 agent 用租户 B 查询 -> 当前 `get` 只有一个参数，期望 `None`
- [x] 反例 4：`max_runs=1` 连跑两次 -> 期望第二次 `QuotaExceeded`
- [x] 反例 5：计划超额仍然执行 -> 期望不调用 agent

## 契约

```python
class AgentManifest(BaseModel):
    ...
    tenant: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

class AgentRegistry(Protocol):
    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None: ...
    async def publish(self, agent: PublishedAgent) -> PublishedAgent: ...

class QuotaPolicy(BaseModel):
    max_runs: int | None = Field(default=None, gt=0)
    window_seconds: float = Field(default=60.0, gt=0)
    max_concurrent: int | None = Field(default=None, gt=0)

class QuotaManager(Protocol):
    def reserve(self, tenant: str, policy: QuotaPolicy) -> AbstractAsyncContextManager[None]: ...
```

- 注册表路径是 `<root>/<tenant>/<id>/<version>.json`。租户来自 manifest，不受调用方控制。
- `get` 校验 manifest 的租户、id、version、digest 与请求一致，否则返回 `None`。
- 路径的租户、id、version 都必须匹配 `^[A-Za-z0-9][A-Za-z0-9._+-]*$`。
- 配额策略必须至少设置 `max_runs` 或 `max_concurrent` 之一。
- 窗口按 `max_runs` 计数，过期槽位释放。
- 并发槽在上下文退出时释放，包括异常路径。
- 先检查再提交：任一限额不满足时，不消耗另一个限额的槽位。
- 超额抛 `QuotaExceeded`，带 `tenant` 和 `limit`。
- `AgentRuntime.run` 和 `PlanExecutor.run` 接受 `quota` 与 `quota_policy`。任一为空则不限。
- 超额写审计：`agent.run` 或 `orchestration.run`，`status=denied`，`error_code=quota_exceeded`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户 id、manifest、运行次数、并发数、成本。
2. **调用方**：CLI、控制台、编排执行器、后续多租户网关。
3. **信任边界**：调用方传入的租户、注册表文件系统、配额管理器。
4. **恶意输入最坏结果**：伪造租户读别人的 agent；路径穿越写文件；配额绕过导致资源耗尽；配额检查和扣减之间的竞态。用 manifest 内租户为准、每段路径校验、单锁检查并提交、超额审计处理。
5. **失败是否泄露信息**：跨租户查询一律 `None`，不区分不存在和无权访问。错误只带租户和限额名。

### 已知边界

- 配额只在单进程内存生效。多副本部署需要共享后端，排在 M5。
- 租户身份仍来自 `Principal.tenant` / manifest，没有接 OIDC 或网关注入。
- 配额按运行次数和并发数计，不按 token 或金额计。
- 注册表迁移：旧布局 `<id>/<version>.json` 不自动迁移，重新发布即可。
- 审计哈希链和篡改检测仍未做。

## 证据

- 反例红: `ImportError: cannot import name 'QuotaPolicy' from 'adk_agent.core'`，2 个测试模块收集失败
- 实现后绿: 配额测试 11 passed
- `check.py --fast` -> 256 passed, 1 skipped，7 步全 PASS
- `check.py --full` -> 256 passed, 1 skipped，9 步全 PASS
- 详见 `docs/evidence/SLICE-028-tenant-quota.txt`
