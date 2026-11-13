# SLICE-064 工件类型与端口

状态: merged
依据: ADR-0008，`docs/contracts/README.md`。

## 意图（要什么，不写怎么写）

ADR-0008 已签。第一刀只落类型和端口，不改行为：新的 `AgentArtifact` 领域类型、`AgentRef` 与 `PublishedAgent` 的加法字段、`ArtifactStore` / `ArtifactLoader` 端口、以及对应 schema。

- `AgentArtifact`：`digest`（`sha256:<64 hex>`）、`media_type`（固定一个值）、`size`（1 到 8 MiB）、`entrypoint`（默认 `agent.py`）、可选 `signature`（128 hex）与 `key_id`。
- `AgentRef` 增加可选 `artifact_digest`；`PublishedAgent` 增加可选 `artifact`。现有字段语义不变。
- 端口进 `core/ports.py`，不引入 I/O。
- `docs/contracts/agent_artifact.schema.json` 由导出脚本生成；`agent_ref` 和 `invocation` 的 schema 随之更新。
- 发布命令和运行时行为不变。

## 新增文件

- `src/adk_agent/core/artifact.py`
- `tests/core/test_artifact.py`
- `docs/contracts/agent_artifact.schema.json`
- `docs/evidence/SLICE-064-artifact-types.txt`

## 修改文件

- `src/adk_agent/core/manifest.py`、`src/adk_agent/core/ports.py`、`src/adk_agent/core/__init__.py`
- `scripts/export_contracts.py`、`docs/contracts/README.md`
- `docs/contracts/agent_ref.schema.json`、`docs/contracts/invocation.schema.json`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
AgentArtifact:
  digest:      "sha256:<64 hex>"
  media_type:  "application/vnd.adk.agent+zip"
  size:        1..8_388_608
  entrypoint:  "<module>.py"（默认 "agent.py"）
  signature:   128 hex | null
  key_id:      ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ | null

AgentRef: + artifact_digest: "sha256:<64 hex>" | null
PublishedAgent: + artifact: AgentArtifact | null

ArtifactStore (Protocol):
  async put(artifact, data: bytes) -> None
  async get(digest: str) -> bytes | None
  async has(digest: str) -> bool

ArtifactLoader (Protocol):
  async load(artifact, store) -> Any
```

## 完成判据（可执行）

- [x] 合法工件可往返 -> `tests/core/test_artifact.py::test_artifact_roundtrip`
- [x] 默认入口与媒体类型 -> `tests/core/test_artifact.py::test_artifact_defaults`
- [x] 非法摘要被拒 -> `tests/core/test_artifact.py::test_rejects_bad_digest`
- [x] 非法媒体类型被拒 -> `tests/core/test_artifact.py::test_rejects_bad_media_type`
- [x] 大小越界被拒 -> `tests/core/test_artifact.py::test_rejects_bad_size`
- [x] 非法入口被拒 -> `tests/core/test_artifact.py::test_rejects_bad_entrypoint`
- [x] 非法签名与 `key_id` 被拒 -> `tests/core/test_artifact.py::test_rejects_bad_signature`
- [x] `AgentRef.artifact_digest` 校验 -> `tests/core/test_artifact.py::test_agent_ref_artifact_digest`
- [x] `PublishedAgent` 携带工件 -> `tests/core/test_artifact.py::test_published_agent_carries_artifact`
- [x] schema 与模型同步 -> `tests/core/test_artifact.py::test_schema_exported`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.core import AgentArtifact` -> 当前 `ImportError`
- [x] 反例 2：`AgentRef(..., artifact_digest="x")` -> 当前 `ValidationError`（extra=forbid）
- [x] 反例 3：`docs/contracts/agent_artifact.schema.json` 不存在 -> 当前无此文件

## 契约（如涉及对外接口）

schemas 由模型生成，按 `docs/contracts/README.md` 的规则先改模型再导出；本切片一次提交模型与导出结果。

## 5 问威胁建模（10 分钟）

1. **数据**：工件摘要、大小、入口、签名和密钥 id。
2. **调用方**：发布命令、注册表、运行时加载器。
3. **信任边界**：模型只描述工件，不执行；执行在 loader 切片。
4. **恶意输入最坏结果**：伪造超长签名或入口路径导致后续加载器路径穿越（缓解：入口只允许 `<module>.py`，大小封顶，摘要固定格式；路径检查在 loader 切片再做一次）。
5. **失败是否泄露信息**：校验错误只报字段与规则，不含工件内容。

## 范围外

- 打包、解包、签名实现与加载器（后续切片）。
- Postgres store 与发布命令。
- 控制面 API。

## 证据

- 反例红: `docs/evidence/SLICE-064-artifact-types.txt` 的 red 段
- 实现后绿: 同文件 green 段，34 个类型与契约用例通过，全量 758 个用例通过
