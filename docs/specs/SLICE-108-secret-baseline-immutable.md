# SLICE-108 密钥基线不被扫描改写

状态: gated
依据: SLICE-107 合入后发现 `detect-secrets scan --baseline` 会改写基线文件。

## 意图（要什么，不写怎么写）

门禁只读 `.secrets.baseline`，绝不写它。已知命中在内存里抵扣，基线外的命中让门禁失败；基线只能由人工评审后更新。

- `check.py` 调 detect-secrets 时不再传 `--baseline`。
- 命中按 `(文件名, hashed_secret)` 与基线比对，路径分隔符统一成正斜杠。
- 基线内命中不计数，基线外命中逐文件计数并失败。

`detect-secrets` 的 `scan --baseline` 把新命中 `merge` 进基线再 `save_to_file`（`.venv/Lib/site-packages/detect_secrets/main.py:85-87`）。门禁跑一次，新密钥就被写进允许清单，下一次扫描即放行。

## 新增文件

- `docs/specs/SLICE-108-secret-baseline-immutable.md`
- `docs/evidence/SLICE-108-secret-baseline-immutable.txt`

## 修改文件

- `scripts/check.py`（命令不再带 `--baseline`，新增内存过滤）
- `tests/test_security_gate.py`（命令与过滤测试）
- `docs/guides/operations.md`（一句：门禁不改写基线）

## 完成判据（可执行）

- [x] 扫描命令不含 `--baseline` -> `::test_secrets_command_does_not_write_baseline`
- [x] 基线内命中抵扣、基线外命中失败 -> `::test_baseline_hits_are_ignored_but_new_hits_fail`
- [x] 扫描后基线文件字节不变 -> 证据 baseline 段
- [x] 本地 `python scripts/check.py --full` 全绿 -> 证据 gate 段
- [ ] PR 的 `gate` 检查通过 -> 证据 ci 段

## 反例（必须在实现前跑红）

- [x] 反例 1：旧命令在临时目录扫描含新密钥的文件后，基线文件多出该命中（证据 red 段）
- [x] 反例 2：过滤器把基线外命中当已知 -> `::test_baseline_hits_are_ignored_but_new_hits_fail` 红

## 契约（如涉及对外接口）

不涉及运行时接口。门禁行为变化写进本 spec 与运行手册。

## 5 问威胁建模（10 分钟）

1. **数据**：工作树文件、`.secrets.baseline`。
2. **调用方**：本地 hook、CI。
3. **信任边界**：开发者提交到本地 hook，push 到 GitHub，CI 到 PR。
4. **恶意输入最坏结果**：新密钥被门禁自动写进基线并放行（缓解：扫描命令不写基线，比对在内存里完成）；路径分隔符不一致导致已知命中未抵扣（缓解：统一成正斜杠，测试覆盖）；基线被绕过（缓解：基线变更进入 diff，需要评审）。
5. **失败是否泄露信息**：门禁只输出文件路径与命中数，不打印明文。

## 范围外

- 历史密钥扫描（仍然不做）。
- 基线条目的自动过期清理。

## 证据

- 反例红：`docs/evidence/SLICE-108-secret-baseline-immutable.txt` 的 red 段
- 基线不变：同文件 baseline 段
- 本地门禁：同文件 gate 段
- PR CI：同文件 ci 段
