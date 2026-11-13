# SLICE-065 工件存储

状态: merged
依据: ADR-0008 第 3 条，SLICE-064。

## 意图（要什么，不写怎么写）

工件类型和端口已就位，还没有实现。这一刀给 `ArtifactStore` 两个实现：文件内容寻址目录用于演示和测试，Postgres 表用于共享部署。

- `FileArtifactStore(root)`：字节写到 `<root>/sha256/<hex>`，临时文件加原子替换。
- `PostgresArtifactStore(url)`：`adk_artifacts(digest, media_type, size, bytes, created_at)`，惰性连接池，沿用配额后端的 DSN 规范化和缺驱动报错。
- 两个实现都在 `put` 时校验 `len(data) == artifact.size` 且 `sha256(data)` 等于 `artifact.digest`，不一致不写入。
- `get` / `has` 前校验 digest 格式，非法值抛 `ArtifactStoreError`，杜绝路径拼接。
- `put` 幂等：同一 digest 重复写不报错、不改内容。
- 不接发布命令和运行时，那是后续切片。

## 新增文件

- `src/adk_agent/registry/artifacts.py`
- `src/adk_agent/registry/artifacts_postgres.py`
- `tests/registry/test_artifacts.py`
- `docs/evidence/SLICE-065-artifact-stores.txt`

## 修改文件

- `src/adk_agent/registry/__init__.py`：导出
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
ArtifactStoreError(Exception)
artifact_digest(data: bytes) -> "sha256:<hex>"

FileArtifactStore(root)
  put(artifact, data) -> None      # 校验后原子写入 <root>/sha256/<hex>
  get(digest) -> bytes | None
  has(digest) -> bool

PostgresArtifactStore(url)
  adk_artifacts(
    digest text PRIMARY KEY,
    media_type text NOT NULL,
    size bigint NOT NULL,
    bytes bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
  )
  插入用 ON CONFLICT (digest) DO NOTHING
```

## 完成判据（可执行）

- [x] 文件存储往返 -> `tests/registry/test_artifacts.py::test_file_roundtrip`
- [x] 文件存储按 digest 寻址 -> `tests/registry/test_artifacts.py::test_file_path_is_addressed`
- [x] 重复写幂等 -> `tests/registry/test_artifacts.py::test_file_put_is_idempotent`
- [x] 大小不符被拒且不落盘 -> `tests/registry/test_artifacts.py::test_file_rejects_size_mismatch`
- [x] 摘要不符被拒且不落盘 -> `tests/registry/test_artifacts.py::test_file_rejects_digest_mismatch`
- [x] 非法 digest 被拒 -> `tests/registry/test_artifacts.py::test_file_rejects_bad_digest`
- [x] 缺失返回 None -> `tests/registry/test_artifacts.py::test_file_missing`
- [x] Postgres 往返（需 `TEST_POSTGRES_URL`） -> `tests/registry/test_artifacts.py::test_postgres_roundtrip`
- [x] Postgres 重复写幂等 -> `tests/registry/test_artifacts.py::test_postgres_put_is_idempotent`
- [x] Postgres 缺失与非法 digest -> `tests/registry/test_artifacts.py::test_postgres_missing_and_bad_digest`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import FileArtifactStore` -> 当前 `ImportError`
- [x] 反例 2：写入与声明摘要不符的数据如果不拒绝，会污染按 digest 的运行 -> `test_file_rejects_digest_mismatch`
- [x] 反例 3：`get("../x")` 若拼进路径就是穿越 -> `test_file_rejects_bad_digest`

## 契约（如涉及对外接口）

不涉及。工件字节存储是内部适配器，接口是 SLICE-064 的 `ArtifactStore` 端口。

## 5 问威胁建模（10 分钟）

1. **数据**：工件字节（代码）、摘要、大小、媒体类型。
2. **调用方**：发布命令和运行时加载器（后续切片）。
3. **信任边界**：进程到文件系统 / Postgres。
4. **恶意输入最坏结果**：路径穿越（缓解：digest 白名单正则，文件名只用 hex）；写入内容与摘要不符（缓解：写前校验）；部分写入（缓解：临时文件加 `os.replace`）；超大工件（模型上限 8 MiB，store 再校验 size 必须等于字节数）。
5. **失败是否泄露信息**：错误只报原因类型，不回显字节或路径以外的内容。

## 范围外

- 打包与签名（SLICE-066）。
- 发布命令接线（SLICE-066）。
- 对象存储和保留策略。

## 证据

- 反例红: `docs/evidence/SLICE-065-artifact-stores.txt` 的 red 段
- 实现后绿: 同文件 green 段，文件存储 7 个用例；设 `TEST_POSTGRES_URL` 后 10 个全过
- 实机: 同文件 live 段。真 Postgres 15 写入两件工件，表内 digest 与大小正确，读回一致
