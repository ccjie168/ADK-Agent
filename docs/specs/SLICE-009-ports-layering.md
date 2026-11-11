# SLICE-009 包骨架、端口与分层门禁（M0-2）

状态: gated
依据: ADR-0002 第 2 条

## 意图（要什么，不写怎么写）

把 `core` 的依赖方向变成可执行的规则。`core` 只依赖领域类型和标准库，不导入任何适配器或框架层。违反时门禁失败，而不是靠文档约定。

同时定义六个已经能定型的端口：`AgentRegistry`、`IdentityProvider`、`SecretProvider`、`PolicyEngine`、`AuditSink`、`TemplateSource`。它们的方法只用 `core` 已有类型。

其余四个端口 `ModelGateway`、`ToolGateway`、`SessionStore`、`OrchestratorStrategy` 推迟到引入各自请求和响应类型的切片。现在定义它们会产生空壳或 `Any` 签名，违反“先减后加”。

## 新增文件

- `src/adk_agent/core/ports.py`
- `scripts/check_layering.py`
- `.importlinter`
- `tests/test_layering.py`

## 修改文件

- `pyproject.toml`：`dev` extra 增加 `import-linter>=2.0`。
- `scripts/check.py`：`FAST_STEPS` 增加 `layering` 步骤。

## 完成判据（可执行）

- [x] `core/ports.py` 定义六个 Protocol -> `tests/test_layering.py::test_ports_defined`
- [x] `lint-imports` 在当前仓库通过 -> `::test_core_isolation`
- [x] 分层合约能抓住违规 -> `::test_contract_catches_violation`
- [x] `check.py --fast` 输出包含 `[PASS] layering` -> 证据
- [x] `check.py --full` 包含 `layering` -> 证据
- [x] `pyproject.toml` 的 `dev` 包含 `import-linter`

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core.ports import AgentRegistry` -> 模块不存在，`ModuleNotFoundError` -> `::test_ports_defined`
- [x] 反例 2：临时包里 `badpkg.core` 导入 `badpkg.adapter` -> `lint-imports` 非零退出 -> `::test_contract_catches_violation`
- [x] 反例 3：仓库缺少 `.importlinter` 或分层步骤缺失 -> `::test_core_isolation` 或门禁失败

## 契约

### 端口

```python
class AgentRegistry(Protocol):
    async def get(self, ref: AgentRef) -> PublishedAgent | None: ...
    async def publish(self, agent: PublishedAgent) -> None: ...

class IdentityProvider(Protocol):
    async def resolve(self, credential: str) -> Principal: ...

class SecretProvider(Protocol):
    async def resolve(self, reference: str) -> str: ...

class PolicyEngine(Protocol):
    async def decide(self, invocation: Invocation, action: str, target: str) -> PolicyDecision: ...

class AuditSink(Protocol):
    async def emit(self, event: AuditEvent) -> None: ...

class TemplateSource(Protocol):
    async def render(self, template_id: str, params: Mapping[str, str]) -> Mapping[str, str]: ...
```

### 分层合约

`adk_agent.core` 不得导入：

- `adk_agent.cli`
- `adk_agent.config`
- `adk_agent.console`
- `adk_agent.factory`
- `adk_agent.models`
- `adk_agent.mcp`

以后新增的适配器模块逐个加入 `forbidden_modules`。

## 5 问威胁建模（10 分钟）

1. **数据**：无业务数据，只有模块依赖图。
2. **调用方**：门禁、开发者、后续 agent。
3. **信任边界**：无网络或文件输入。
4. **恶意输入最坏结果**：适配器依赖漏进 `core`，插件加载时拖入错误层或循环依赖。分层合约在门禁中拒绝。
5. **失败是否泄露信息**：lint 输出只包含模块名和合约名，不含密钥或数据。

## 证据

- 反例红: `pytest tests/test_layering.py -q` -> `2 failed, 1 passed`。`test_ports_defined` 报 `ModuleNotFoundError`，`test_core_isolation` 报 `Could not read any configuration`，负向测试已能抓到违规。
- 实现后绿: `pytest tests/test_layering.py -q` -> 3 passed
- `check.py --fast` -> `[PASS] layering`，46 tests，ALL PASS
- `check.py --full` -> 8 步全 PASS
- 详见 `docs/evidence/SLICE-009-ports-layering.txt`
