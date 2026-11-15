# SLICE-109 发布流水线与 digest 回写

状态: gated
依据: ADR-0018 把镜像推送与 digest 回写留给发布流水线；镜像仓库用自建 registry。

## 意图（要什么，不写怎么写）

补上发行完整性的最后一步。发布 workflow 先跑完整门禁与镜像扫描，再把镜像推到自建 registry，输出 `image@digest`；回写脚本把 digest 固定进两个清单。

- 新增 `.github/workflows/release.yml`。只有 `workflow_dispatch`，只在 `master` 运行，先 `check.py --full --strict`，再 Trivy，扫描通过后才 `docker push`。
- registry 地址由输入 `image` 给出，凭据只从 `REGISTRY_USERNAME` / `REGISTRY_PASSWORD` 读取，runner 由输入选择，适应私有网络。
- 推送后用 `docker buildx imagetools inspect` 取 digest，写进 `release.txt` 与 job summary。
- 新增 `scripts/release_digest.py`。校验镜像引用与 digest，把两个清单里所有 `image: ...@sha256:<64 hex>` 行替换成新引用，幂等并保留行尾。
- 回写仍走正常 PR，由操作员在推送成功后本地执行脚本并提交。

## 新增文件

- `.github/workflows/release.yml`
- `scripts/release_digest.py`
- `tests/test_release_digest.py`
- `docs/specs/SLICE-109-release-pipeline.md`
- `docs/evidence/SLICE-109-release-pipeline.txt`

## 修改文件

- `docs/guides/operations.md`（发布步骤）
- `docs/specs/ROADMAP.md`（切片登记）

## 完成判据（可执行）

- [x] 带 tag、带 digest、无 registry 前缀的镜像引用被拒绝 -> `tests/test_release_digest.py::test_validate_image`
- [x] 非 `sha256:<64 hex>` 的 digest 被拒绝 -> `::test_validate_digest`
- [x] 清单里每条 digest 行都被替换，CRLF 保留 -> `::test_rewrite_pins_every_digest_line`
- [x] 重复执行结果不变 -> `::test_rewrite_is_idempotent`
- [x] CLI 写入指定文件 -> `::test_cli_pins_files`
- [x] workflow 仅手动触发、仅 master、先门禁与扫描后推送 -> `::test_release_workflow_order`
- [x] 本地 `python scripts/check.py --full` 全绿 -> 证据 gate 段
- [ ] PR 的 `gate` 检查通过 -> 证据 ci 段
- [ ] 真实推送与回写 -> 由操作员在自建 registry 上执行，结果补进证据 release 段

## 反例（必须在实现前跑红）

- [x] 反例 1：脚本与测试先写，`scripts/release_digest.py` 不存在 -> `ModuleNotFoundError`
- [x] 反例 2：接受 `registry.local:5000/adk-agent:latest` -> 必须抛 `ValueError`
- [x] 反例 3：workflow 若先推送后扫描 -> 顺序断言红

## 契约（如涉及对外接口）

不涉及运行时接口。新增一个手动 workflow 与一个运维脚本，输入、secret 名与命令写进运行手册。

## 5 问威胁建模（10 分钟）

1. **数据**：镜像字节、registry 凭据、digest、部署清单。
2. **调用方**：发布操作员、GitHub Actions、自建 registry。
3. **信任边界**：GitHub runner 到私有 registry；仓库到集群。
4. **恶意输入最坏结果**：凭据写进仓库（缓解：只用 secrets，输入里不接受密码）；推送未通过扫描的镜像（缓解：门禁与 Trivy 在 push 之前）；tag 漂移（缓解：清单只认 digest）；从非 master 发布（缓解：job 条件锁 master）；workflow 被误触发（缓解：只有 workflow_dispatch）。
5. **失败是否泄露信息**：日志不打印密码；digest 与镜像引用可公开。

## 范围外

- 自动开 PR 回写 digest。回写走人工 PR，保留评审。
- 多架构镜像、镜像签名、registry 本身的部署与证书。
- 用 digest 替换 `Dockerfile` 的基础镜像固定，那是显式提交。

## 证据

- 反例红：`docs/evidence/SLICE-109-release-pipeline.txt` 的 red 段
- 本地门禁：同文件 gate 段
- PR CI：同文件 ci 段
- 真实发布：同文件 release 段（合入后由操作员补）
