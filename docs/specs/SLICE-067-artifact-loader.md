# SLICE-067 工件加载与验签

状态: merged
依据: ADR-0008 第 3、4、6 条，SLICE-065，SLICE-066。

## 意图（要什么，不写怎么写）

工件能发布、能存储，但还不能运行。这一刀加进程内加载器和可信密钥表，让注册的工件可以按引用加载成 agent。

- `registry/trust.py`：`TrustStore`（`key_id -> Ed25519 公钥`）与 `ArtifactTrustError`；从 JSON 映射或环境变量 `ADK_ARTIFACT_KEYS` 读取。
- `registry/loader.py`：`InProcessArtifactLoader`、`ArtifactLoadError`、`load_agent`。
- loader 从 store 取字节后重新校验摘要与大小，再解析 zip。解包前检查每个条目：拒绝绝对路径、`..`、反斜杠、符号链接、超出白名单的名字、总解压大小超过 8 MiB、条目数超过 64。只读 `manifest.json` 与入口模块源码，不落地执行外部路径。
- 入口模块在独立命名空间执行，必须暴露 `agent` 或 `root_agent`，且是 ADK `BaseAgent`、`name` 等于 manifest 的 `id`。
- `load_agent(*, registry, ref, tenant, store, loader, trust)`：按 `AgentRef`（含 digest）取版本，要求有工件，先验签再加载。版本不存在、无工件、验签失败、加载失败都抛 `ArtifactLoadError` 或信任错误。
- 不接控制台和 MCP 的启动参数，那是 SLICE-068。

## 新增文件

- `src/adk_agent/registry/trust.py`
- `src/adk_agent/registry/loader.py`
- `tests/registry/test_artifact_loader.py`
- `docs/evidence/SLICE-067-artifact-loader.txt`

## 修改文件

- `src/adk_agent/registry/__init__.py`：导出
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
TrustStore(keys: Mapping[str, bytes])       # 原始 32 字节公钥
  from_json(json_text) / from_env(var="ADK_ARTIFACT_KEYS")
  verify(artifact: AgentArtifact) -> None   # 缺签名/未知 key_id/验签失败 -> ArtifactTrustError

InProcessArtifactLoader()
  async load(artifact, store) -> BaseAgent

load_agent(*, registry, ref: AgentRef, tenant, store, loader, trust) -> BaseAgent
  registry.get -> 校验 artifact 存在 -> trust.verify -> loader.load
```

## 完成判据（可执行）

- [x] 验签通过 -> `tests/registry/test_artifact_loader.py::test_trust_verifies`
- [x] 未知 key_id 被拒 -> `tests/registry/test_artifact_loader.py::test_trust_unknown_key`
- [x] 缺签名被拒 -> `tests/registry/test_artifact_loader.py::test_trust_requires_signature`
- [x] 篡改签名被拒 -> `tests/registry/test_artifact_loader.py::test_trust_rejects_tamper`
- [x] 正常工件加载成 agent -> `tests/registry/test_artifact_loader.py::test_loads_agent`
- [x] 缺字节被拒 -> `tests/registry/test_artifact_loader.py::test_missing_bytes`
- [x] 字节与摘要不符被拒 -> `tests/registry/test_artifact_loader.py::test_digest_mismatch`
- [x] 路径穿越条目被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_traversal`
- [x] 绝对路径被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_absolute`
- [x] 符号链接被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_symlink`
- [x] 白名单外文件被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_unexpected_file`
- [x] 缺入口被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_missing_entrypoint`
- [x] 名称不符被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_name_mismatch`
- [x] 模块不暴露 agent 被拒 -> `tests/registry/test_artifact_loader.py::test_rejects_no_agent`
- [x] `load_agent` 验签后加载 -> `tests/registry/test_artifact_loader.py::test_load_agent`
- [x] `load_agent` 拒绝无工件的版本 -> `tests/registry/test_artifact_loader.py::test_load_agent_without_artifact`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import InProcessArtifactLoader` -> 当前 `ImportError`
- [x] 反例 2：含 `../evil.py` 的 zip 若直接解包就是穿越 -> `test_rejects_traversal`
- [x] 反例 3：未验签就加载 -> `test_load_agent` 用错误公钥断言失败

## 契约（如涉及对外接口）

不新增对外 HTTP 接口。可信密钥表的环境变量名在此约定，CLI 接线时写进 `cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：工件代码、manifest、签名、公钥。
2. **调用方**：控制台 / MCP 启动路径（后续切片）和库调用方。
3. **信任边界**：已发布代码到平台进程。这是明确的代码执行边界。
4. **恶意输入最坏结果**：未签名代码执行（缓解：先验签，密钥表按部署配置）；zip 穿越或符号链接写穿临时目录（缓解：不落地解包，直接读成员；条目白名单与路径检查）；zip 炸弹（缓解：总解压大小上限与条目数上限）；冒充其他 agent（缓解：`agent.name == manifest.id`）。进程内执行不是沙箱，这一点在 ADR 与文档中明确。
5. **失败是否泄露信息**：错误只报阶段与原因类型，不回显公钥或代码内容。

## 范围外

- 沙箱 / 容器加载器。
- 自动安装 `requirements.txt`。
- 控制台与 MCP 的启动参数（SLICE-068）。
- 公钥轮换流程；密钥表按部署整体替换。

## 证据

- 反例红: `docs/evidence/SLICE-067-artifact-loader.txt` 的 red 段
- 实现后绿: 同文件 green 段，16 个用例与全量 800 个用例通过
- 实机: 同文件 live 段。用 SLICE-066 发布的真工件加载出 `bot` 的 `LlmAgent`；错误公钥报签名无效，缺字节报找不到工件
