# SLICE-107 密钥扫描加固

状态: gated
依据: 用户要求增强密钥扫描；不新增依赖，不做历史扫描。

## 意图（要什么，不写怎么写）

把密钥扫描从“只扫工作树、整目录跳过证据”改成“扫证据目录、已知命中进基线”，并让已接受漏洞的到期日真正生效。

- `docs/evidence` 不再整目录排除。扫描改用一个 tracked 的 `.secrets.baseline`，已审的 17 处命中（16 个本地开发 DSN，1 个 `secrets` 标签误报）进基线，新增命中让门禁失败。
- `check.py` 的 secrets 步骤使用 `--baseline .secrets.baseline`。
- `check.py` 与 `sbom.py` 按 `.trivyignore.yaml` 的 `expired_at` 过滤接受清单，过期项不再被 `pip-audit` 与 SBOM 忽略。
- 文档记录 GitHub 侧已启用 secret scanning、push protection 和 Dependabot security updates；自定义 pattern 与 validity checks 需要付费套餐。

## 新增文件

- `.secrets.baseline`
- `docs/specs/SLICE-107-secret-scan-hardening.md`
- `docs/evidence/SLICE-107-secret-scan-hardening.txt`

## 修改文件

- `scripts/check.py`（证据目录扫描、baseline、到期过滤）
- `scripts/sbom.py`（到期过滤）
- `tests/test_security_gate.py`（baseline 与到期测试）
- `docs/guides/operations.md`（值守检查）

## 完成判据（可执行）

- [x] `docs/evidence` 不再整目录排除 -> `SECRET_EXCLUDES` 不含 `docs[\\/]evidence`
- [x] baseline 覆盖已知命中 -> `tests/test_security_gate.py::test_secrets_scan_uses_baseline`
- [x] 过期风险不再被忽略 -> `::test_expired_risks_are_not_ignored`
- [x] 本地 `python scripts/check.py --full` 全绿 -> 证据 gate 段
- [x] PR 的 `gate` 检查通过 -> 证据 ci 段

## 反例（必须在实现前跑红）

- [x] 反例 1：去掉 `docs/evidence` 排除且不带 baseline -> secrets 步骤报 17 处命中
- [x] 反例 2：`expired_at` 已过期的条目仍被忽略 -> `test_expired_risks_are_not_ignored` 红

## 契约（如涉及对外接口）

不涉及运行时接口。仓库根新增 `.secrets.baseline`，门禁行为变化写进本 spec 与运行手册。

## 5 问威胁建模（10 分钟）

1. **数据**：工作树文件、证据文件、密钥基线、已接受漏洞清单。
2. **调用方**：本地 hook、CI、发布操作员。
3. **信任边界**：开发者提交到本地 hook，push 到 GitHub，CI 到 PR。
4. **恶意输入最坏结果**：密钥粘进证据文件（缓解：去掉整目录排除）；基线掩盖新密钥（缓解：基线按文件与哈希匹配，新行仍会命中）；接受风险过期后继续忽略（缓解：按 `expired_at` 过滤）；历史泄露（范围外，用户明确不做）。
5. **失败是否泄露信息**：门禁只输出文件路径与命中数，不打印明文。

## 范围外

- 历史密钥扫描（gitleaks 或 trufflehog）。
- GitHub 自定义 pattern 与 validity checks（付费套餐）。
- 历史中的本地开发 DSN 重写。

## 证据

- 反例红：`docs/evidence/SLICE-107-secret-scan-hardening.txt` 的 red 段
- 基线：同文件 baseline 段
- 本地门禁：同文件 gate 段
- PR CI：同文件 ci 段
