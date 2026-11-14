# SLICE-102 构建供应链收尾

状态: gated
依据: ADR-0018 第 2、3 条；`docs/evidence/SLICE-101-release-integrity.txt` 的 notes 残留项。

## 意图（要什么，不写怎么写）

SLICE-101 锁住了运行时依赖，但构建侧还有两个口子。这一刀让构建过程也不再从索引无哈希拉取任何包，并把 CI 的第三方 action 固定到 commit SHA。不改运行时行为，不新增运行时功能依赖，不推送镜像。

- 构建后端进入锁。`[build-system].requires` 目前只有 `hatchling`，Dockerfile 和 CI 用 build isolation，构建项目时从索引拉取 hatchling，没有哈希校验。把 hatchling 及其传递依赖锁进 `requirements/runtime.lock` 和 `requirements/dev.lock`，构建改用 `--no-build-isolation`。
- dev 锁用 `--allow-unsafe` 固定 `pip` 与 `setuptools`。`pip-tools` 依赖未固定的 `setuptools`，CI 的 `--require-hashes` 安装否则会失败。
- CI 的 action 按 commit SHA 固定。`actions/checkout@v4`、`actions/setup-python@v5`、`aquasecurity/setup-trivy@v0.3.1`、`actions/upload-artifact@v4` 都改为 `@<40 位 SHA>`，行尾注释保留原版本号。Trivy 用 `setup-trivy` 安装固定版本，再直接运行 `trivy image`。原先的 `trivy-action@0.28.0` 是复合 action，内部引用已删除的 `setup-trivy@v0.2.1`，首次 CI 运行即失败。
- 镜像推送与 digest 回写不在本刀范围。它需要 registry 地址与凭据，属于运维决策。

## 新增文件

- `docs/evidence/SLICE-102-build-supply-chain.txt`
- `docs/specs/SLICE-102-build-supply-chain.md`

## 修改文件

- `pyproject.toml`（新增 `build` extra，内容为 `hatchling`）
- `requirements/runtime.lock`、`requirements/dev.lock`（加入构建后端与传递依赖）
- `Dockerfile`（项目安装改为 `--no-build-isolation`）
- `.github/workflows/ci.yml`（项目安装改为 `--no-build-isolation`，四个 action 固定 SHA）
- `tests/test_release_lock.py`（新增断言）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`（完成时）

## 数据形状

```text
requirements/runtime.lock   运行时集合 + hatchling 及其构建依赖，全部带哈希
requirements/dev.lock       开发集合 + hatchling 及其构建依赖，全部带哈希

Dockerfile:
  pip install --require-hashes -r requirements/runtime.lock
  pip install --no-build-isolation --no-deps .

.github/workflows/ci.yml:
  pip install --require-hashes -r requirements/dev.lock
  pip install --no-build-isolation --no-deps .
  uses: <owner>/<action>@<40 位 SHA>  # vX.Y.Z
```

## 完成判据（可执行）

- [x] 两个锁都包含 `hatchling`，且每条带哈希 -> `tests/test_release_lock.py::test_build_backend_is_locked`
- [x] Dockerfile 与 CI 安装项目时使用 `--no-build-isolation` -> `::test_builds_disable_build_isolation`
- [x] CI 的每个 `uses:` 都是 40 位 SHA，注释保留版本 -> `::test_actions_are_pinned_by_sha`
- [x] 镜像可构建，容器 `/healthz` 返回 200 -> 证据文件 image 段
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：`rg -c "^hatchling==" requirements/runtime.lock requirements/dev.lock` -> 当前两个文件都是 0
- [x] 反例 2：`rg -c "no-build-isolation" Dockerfile .github/workflows/ci.yml` -> 当前两个文件都是 0
- [x] 反例 3：`rg -n "uses: .*@v[0-9]|trivy-action@0\.28\.0" .github/workflows/ci.yml` -> 当前 4 条 tag 引用
- [x] 反例 4：新加断言先红 -> `pytest tests/test_release_lock.py -k "build_backend or build_isolation or actions_pinned"` 失败

## 契约（如涉及对外接口）

不涉及。环境变量、CLI 与运行时接口不变。

## 5 问威胁建模（10 分钟）

1. **数据**：构建后端包、action 代码、镜像层、SBOM、构建日志。
2. **调用方**：CI、发布操作员、构建机。
3. **信任边界**：包索引到构建、GitHub tag 到 workflow、CI 到产物。
4. **恶意输入最坏结果**：构建后端被替换（缓解：哈希锁）；action tag 被移到恶意提交（缓解：SHA 固定）；未固定的构建脚本执行（缓解：`--no-build-isolation` 加锁）；CI 凭据泄露（本刀不引入 registry 凭据）。
5. **失败是否泄露信息**：构建只读公共索引，日志不打印 token，SBOM 不含凭据。

## 范围外

- 镜像推送、digest 自动回写、registry 凭据。
- 镜像签名与 provenance（cosign、attestation）。
- Renovate/Dependabot 自动升级。
- 逐字节可复现构建。

## 证据

- 反例红：`docs/evidence/SLICE-102-build-supply-chain.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 镜像：同文件 image 段
