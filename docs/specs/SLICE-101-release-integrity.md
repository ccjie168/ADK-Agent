# SLICE-101 发行完整性

状态: merged
依据: ADR-0018 第 1 至 4 条。

## 意图（要什么，不写怎么写）

门禁证明的是当前依赖组合，不是要发布的镜像。这一刀把依赖锁成可复现的集合，让 CI 按锁安装并扫描要发布的镜像，部署按 digest 引用。不改运行时行为，不新增运行时依赖。

- 提交 `requirements/runtime.lock` 与 `requirements/dev.lock`，全部 `==` 且带 `--hash=sha256:`，在 `python:3.13-slim` 里编译。
- Dockerfile 用 `--require-hashes` 安装运行时锁；基础镜像按 digest 固定。
- CI 用 dev 锁安装后跑 `scripts/check.py --full --strict`，再构建镜像、Trivy 扫描、上传 SBOM。
- 多副本清单与单机清单不再使用 `:latest`，改用 `@sha256:` digest 占位，并在手册写明 digest 来源。
- `pip-tools` 只进开发依赖；`pyproject.toml` 的范围仍是升级入口。
- 运行时镜像包含 `litellm`，因为模型默认回退是 LiteLLM DeepSeek，国内模型也走这条通道。

## 新增文件

- `requirements/runtime.lock`
- `requirements/dev.lock`
- `tests/test_release_lock.py`
- `.trivyignore.yaml`（携带 statement 与到期日的接受风险）
- `docs/evidence/SLICE-101-release-integrity.txt`
- `docs/specs/SLICE-101-release-integrity.md`

## 修改文件

- `pyproject.toml`（dev 增加 `pip-tools`）
- `Dockerfile`
- `.github/workflows/ci.yml`
- `deploy/k8s/multi-replica.yaml`、`deploy/k8s/deployment.yaml`
- `docs/guides/operations.md`（发行与升级一节）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
requirements/runtime.lock   .[claude,litellm,http,oidc,publish,redis] + 传递依赖, 全部带哈希
requirements/dev.lock       .[dev,claude,litellm,http,oidc,publish,redis] + 传递依赖, 全部带哈希

Dockerfile:
  FROM python:3.13-slim@sha256:<digest>
  RUN pip install --require-hashes -r requirements/runtime.lock
  RUN pip install --no-deps .

CI gate 作业:
  pip install --require-hashes -r requirements/dev.lock
  python scripts/check.py --full --strict
  docker build -t adk-agent:${{ github.sha }} .
  trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 \n    --ignorefile .trivyignore.yaml ...
  python scripts/sbom.py -o sbom.json
  upload sbom

清单:
  image: adk-agent@sha256:<digest>
  禁止 adk-agent:latest
```

## 完成判据（可执行）

- [x] 两个锁文件都存在、全部 `==`、每条都有 `--hash=sha256:` -> `tests/test_release_lock.py::test_lock_files_are_fully_pinned`
- [x] 锁覆盖 pyproject 的顶层依赖与 dev 工具，且含 `litellm` -> `::test_lock_files_cover_declared_dependencies`
- [x] Dockerfile 只用锁安装运行时依赖 -> `::test_dockerfile_installs_from_runtime_lock`
- [x] CI 从 dev 锁安装、构建并扫描镜像 -> `::test_ci_uses_locks_builds_and_scans`
- [x] 清单不使用 `:latest`，镜像按 digest 引用 -> `::test_manifests_pin_image_digest`
- [x] 同一运行时锁两次下载得到相同文件哈希 -> 证据文件 reproducible 段
- [x] 镜像可构建，容器 `/healthz` 返回 200 -> 证据文件 image 段
- [x] 镜像扫描无 HIGH/CRITICAL 可修复项，或忽略项有到期日 -> 证据文件 scan 段
- [x] `python scripts/check.py --full` 全绿 -> 证据文件 gate 段

## 反例（必须在实现前跑红）

- [x] 反例 1：`pytest tests/test_release_lock.py` -> 当前没有锁文件，收集或读取失败
- [x] 反例 2：`grep -c "require-hashes" Dockerfile .github/workflows/ci.yml` -> 当前为 0
- [x] 反例 3：`grep -c "image: adk-agent:latest" deploy/k8s/*.yaml` -> 当前多副本 4 处、单机 1 处
- [x] 反例 4：`grep -c "trivy\|docker build" .github/workflows/ci.yml` -> 当前为 0

## 契约（如涉及对外接口）

不涉及运行时接口。环境变量与 CLI 不变。新增的是构建与发布契约，写进 `docs/guides/operations.md` 与 ADR-0018。

## 5 问威胁建模（10 分钟）

1. **数据**：依赖图、轮子哈希、镜像层、SBOM、构建日志。
2. **调用方**：CI、发布操作员、Kubernetes。
3. **信任边界**：包索引到构建、镜像仓库到集群、CI 到产物。
4. **恶意输入最坏结果**：传递依赖被替换（缓解：`--require-hashes`）；浮动标签指向别的镜像（缓解：digest 引用）；基础镜像带高危漏洞（缓解：Trivy 扫描与显式 digest 更新）；构建脚本从浮动的 action 拉取（缓解：action 固定版本，SHA 固定列为后续项）。
5. **失败是否泄露信息**：构建只访问公共依赖；日志不打印 token；SBOM 不含凭据。

## 范围外

- 镜像签名与证明（cosign、attestation）。
- CI 推送 registry 并自动回写 digest。
- Renovate/Dependabot 自动升级。
- `gemini`、`litellm` 的默认镜像（需要时另建）。
- Windows 开发环境的逐字节可复现。

## 证据

- 反例红：`docs/evidence/SLICE-101-release-integrity.txt` 的 red 段
- 实现后绿：同文件 green 与 gate 段
- 可复现：同文件 reproducible 段
- 镜像与扫描：同文件 image 与 scan 段
