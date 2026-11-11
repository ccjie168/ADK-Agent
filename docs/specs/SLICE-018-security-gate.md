# SLICE-018 安全门强制（M1-6）

状态: gated
依据: ADR-0001、ADR-0002，用户要求把安全检查变成不可绕过

## 意图（要什么，不写怎么写）

当前的安全检查是“可用的”，不是“强制的”。`check.py --full` 会跑 bandit、pip-audit 和 detect-secrets，CI 也会跑，但提交本身没有 hook，推送后 CI 才检查，`--fast` 不含 SAST 和依赖审计。

这一刀把已有的检查变成提交前和 CI 的双层强制，不引入新的安全平台。

分两段。

- Phase A，不新增运行时依赖，现在就能做：原生 pre-commit hook、CI 必需检查、bandit 覆盖 `scripts`、spec 威胁模型门禁。
- Phase B，需要新 ADR 或工具决策：依赖锁、历史密钥扫描、镜像扫描、SBOM 校验与签名、日志脱敏。

Phase B 不在这一刀里实现。它需要先登记工具和依赖，按 ADR-0001 走。

## 新增文件

- `.githooks/pre-commit`
- `scripts/install_hooks.py`
- `scripts/check_specs.py`
- `tests/test_security_gate.py`

## 修改文件

- `scripts/check.py`：新增 `specs` 步骤，bandit 覆盖 `scripts`，支持无模块脚本步骤
- `.github/workflows/ci.yml`：保持 `--full --strict`，新增 concurrency 和失败摘要
- `docs/specs/ROADMAP.md`：登记 SLICE-017、SLICE-018
- `docs/specs/_template.md`：把威胁模型标成必填

## 完成判据（Phase A，可执行）

- [x] `.githooks/pre-commit` 调用 `check.py --full`，优先使用 `.venv` 的 Python -> `tests/test_security_gate.py::test_pre_commit_calls_full_gate`
- [x] `scripts/install_hooks.py` 设置 `core.hooksPath=.githooks` -> `::test_install_hooks_sets_hooks_path`
- [x] `scripts/check_specs.py` 拒绝缺少威胁模型的新 slice -> `::test_spec_without_threat_model_fails`
- [x] 缺威胁模型的 merged slice 被跳过 -> `::test_merged_slice_is_grandfathered`
- [x] `check.py --full` 包含 `specs` 步骤 -> 证据
- [x] bandit 扫描 `src` 和 `scripts`，预期 `subprocess` 用法有带理由的 `# nosec` -> 证据
- [x] CI 运行 `check.py --full --strict` -> `.github/workflows/ci.yml`
- [x] 分支保护命令写进文档，实际开启前需要批准

## 反例（必须在实现前跑红）

- [x] 反例 1：新建一个缺 `## 5 问威胁建模` 的 slice -> `check_specs.py` 退出 1 -> `test_spec_without_threat_model_fails`
- [x] 反例 2：merged slice 缺该节 -> 跳过，退出 0 -> `test_merged_slice_is_grandfathered`
- [x] 反例 3：未安装 hook -> `git config core.hooksPath` 为空 -> `test_install_hooks_sets_hooks_path`
- [x] 反例 4：`check.py --full` 输出没有 `[PASS] specs` -> 门禁缺口

## 契约

### pre-commit hook

```sh
#!/bin/sh
PY=python
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; fi
exec "$PY" scripts/check.py --full
```

安装：`python scripts/install_hooks.py`，执行 `git config core.hooksPath .githooks`。

hook 可以用 `--no-verify` 绕过，所以 CI 和分支保护是第二层，不互相替代。

### spec 门禁

`scripts/check_specs.py` 扫描 `docs/specs/SLICE-*.md`。

- 状态为 `planned`、`in_progress`、`review`、`gated` 的 slice 必须包含：`## 意图`、`## 完成判据`、`## 反例`、`## 5 问威胁建模`、`## 证据`。
- 状态为 `merged` 的 slice 豁免，避免改写历史。
- 缺任一节，退出 1，并列出文件和缺失节名。

### bandit

`check.py` 的 sast 步骤改为扫描 `src` 和 `scripts`。

`scripts/check.py` 和 `scripts/sbom.py` 的 `subprocess` 调用是预期行为，加 `# nosec B603 B607` 并在旁边写明理由。除此之外不允许跳过。

### CI

`.github/workflows/ci.yml` 继续保持 `python scripts/check.py --full --strict`。

新增：

- `concurrency` 按 ref 取消旧运行。
- 门禁失败时输出最后 50 行，便于定位。
- 分支保护要求 `ci / gate` 通过。命令写在文档里，实际开启前需要人工批准。

### 分支保护（未应用）

在 GitHub 仓库 `Settings -> Branches` 为 `master` 添加规则：

- Require status checks to pass before merging。
- 选择 `ci / gate`。
- 不允许绕过上述设置。

这是外向变更，本次没有执行。需要明确批准后再开启。

### Phase B 不在本切片

以下需要新 ADR 或工具决策，单独排期：

- 运行时依赖锁，CI 从锁安装，SBOM 从锁生成。
- 历史密钥扫描（gitleaks 或 trufflehog）。
- 镜像构建与 Trivy 扫描。
- SBOM 校验与签名。
- 日志脱敏。它会改变 `test_chat_failure_is_logged` 对 `exc_info` 的断言，需要单独批准并更新测试判据。

## 5 问威胁建模（10 分钟）

1. **数据**：提交内容、CI 日志、依赖清单、SBOM。
2. **调用方**：开发者、CI、后续 agent。
3. **信任边界**：本地 git hook、GitHub Actions、依赖源。
4. **恶意输入最坏结果**：绕过 hook 推送未扫描代码；依赖投毒；历史中的密钥未被发现。hook 加 CI 双层、`--strict`、后续锁和扫描分别处理。
5. **失败是否泄露信息**：hook 和 CI 输出只包含检查名、文件路径和失败摘要，不打印环境变量或密钥。

## 证据

- 反例红: 安全门测试在脚本和 hook 实现前无法通过；`scripts/check_specs.py` 不存在时 specs 步骤无法运行
- 实现后绿: `tests/test_security_gate.py` 7 passed；`check.py --fast` 110 tests，含 `[PASS] specs`
- `check.py --full` -> 110 tests，含 `[PASS] sast`，ALL PASS
- hook 已安装，`core.hooksPath=.githooks`
- 分支保护未应用，需要批准
- 详见 `docs/evidence/SLICE-018-security-gate.txt`
