# SLICE-066 发布带工件与签名

状态: planned
依据: ADR-0008 第 1、2、4、5 条，SLICE-064，SLICE-065，`docs/contracts/cli.md`。

## 意图（要什么，不写怎么写）

工件存储已就位，发布命令还只写 manifest。这一刀让 `publish` 可以附加工件：确定性打包、Ed25519 签名、字节入 store、元数据入注册表。

- 新增 `registry/packaging.py`：`pack_agent(source)`、`read_artifact_zip(path)`、`PackagingError`。
- 新增 `registry/signing.py`：`load_private_key`、`sign_digest`、`verify_digest`、`PublishUnavailable`。
- `published_from` 接受可选 `artifact`。
- `publish` 增加 `--artifact DIR|ZIP`、`--key FILE`、`--key-id ID`、`--artifact-dir DIR`，以及环境变量 `ARTIFACT_URL`。
- 工件字节先入 store，再写注册表；注册表冲突时工件可能成为孤儿，不阻塞。
- 新增可选 extra `publish = ["cryptography>=42"]`，缺依赖时发布失败并给出安装提示。
- 不带 `--artifact` 的发布行为不变。

## 新增文件

- `src/adk_agent/registry/packaging.py`
- `src/adk_agent/registry/signing.py`
- `tests/registry/test_packaging.py`
- `tests/registry/test_signing.py`
- `tests/test_cli_publish_artifact.py`
- `docs/evidence/SLICE-066-publish-artifact.txt`

## 修改文件

- `src/adk_agent/registry/manifest.py`：`published_from(..., artifact=None)`
- `src/adk_agent/registry/__init__.py`：导出
- `src/adk_agent/cli.py`：publish 参数与流程
- `pyproject.toml`：`publish` extra
- `docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
pack_agent(source) -> bytes
  # 读 source/manifest.json 校验；入口 source/agent.py 必须存在
  # 只打包 manifest.json、agent.py、requirements.txt、README.md（存在才打）
  # 条目排序、时间 1980-01-01、权限 0644、ZIP_STORED

read_artifact_zip(path) -> (bytes, AgentManifest)
  # 缺 manifest.json 或内容不合法 -> PackagingError

sign_digest(digest: str, key) -> 128 hex
verify_digest(digest, signature, public_key) -> bool

publish --artifact ... --key ... --key-id ...
  AgentArtifact(digest=sha256(bytes), size=len, entrypoint="agent.py",
                signature=sign_digest(digest, key), key_id=id)
```

## 完成判据（可执行）

- [ ] 打包是字节级确定的 -> `tests/registry/test_packaging.py::test_pack_is_deterministic`
- [ ] 只打包允许的文件 -> `tests/registry/test_packaging.py::test_pack_includes_allowed_files`
- [ ] zip 条目时间与权限固定 -> `tests/registry/test_packaging.py::test_zip_entries_are_normalized`
- [ ] 缺 manifest 或入口被拒 -> `tests/registry/test_packaging.py::test_pack_requires_manifest_and_entrypoint`
- [ ] 读取 zip 校验 manifest -> `tests/registry/test_packaging.py::test_read_zip_checks_manifest`
- [ ] 签名可验、篡改失败 -> `tests/registry/test_signing.py::test_sign_and_verify`
- [ ] 错误公钥验签失败 -> `tests/registry/test_signing.py::test_wrong_key_fails`
- [ ] 发布带工件写入注册表与 store -> `tests/test_cli_publish_artifact.py::test_publish_with_artifact`
- [ ] zip 输入发布 -> `tests/test_cli_publish_artifact.py::test_publish_with_zip`
- [ ] 缺 key 或不给 store 退出 1 -> `tests/test_cli_publish_artifact.py::test_publish_requires_key`
- [ ] manifest 不符的 zip 被拒 -> `tests/test_cli_publish_artifact.py::test_publish_rejects_mismatched_zip`
- [ ] 不带工件的发布不变 -> 既有 `tests/registry/*` 全过
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`from adk_agent.registry import pack_agent` -> 当前 `ImportError`
- [ ] 反例 2：`publish --artifact ...` -> 当前 argparse 退出 2（参数不存在）
- [ ] 反例 3：工件字节与声明摘要不符仍发布 -> 由 `test_publish_with_artifact` 的反向断言（store 内摘要一致）覆盖

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/cli.md` 的 publish 一节。

## 5 问威胁建模（10 分钟）

1. **数据**：agent 源码、manifest、PEM 私钥、签名、工件字节。
2. **调用方**：发布者（运维或研发）。
3. **信任边界**：私钥文件到 CLI；打包目录到 zip；zip 到注册表。
4. **恶意输入最坏结果**：私钥路径指向仓库或被打进工件（缓解：打包白名单只含四个文件，私钥不在其中）；zip 输入夹带与 manifest 不符的代码（缓解：读取时校验 manifest 完全一致）；超限工件（8 MiB 上限）；确定性被文件名或时间破坏（固定排序与时间）。私钥不出现在命令行以外？`--key` 是路径，不是密钥本身。
5. **失败是否泄露信息**：错误只报原因，不回显私钥或密钥内容。

## 范围外

- 可信公钥表与加载时验签（SLICE-067）。
- 密钥生成命令与 KMS。
- 自动依赖安装。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
