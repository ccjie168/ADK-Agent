# SLICE-005 `check.py --full` 累积执行

状态: merged

## 意图（要什么，不写怎么写）

`--full` 是发布前的完整门禁，必须覆盖 `--fast` 的全部检查，再追加 sast 与 deps。
当前实现二选一，`--full` 会漏掉 format / lint / types / test。

## 完成判据（可执行）

- [x] 判据 1：`--fast` 返回 `FAST_STEPS` -> `tests/test_check_gate.py::test_fast_selection`
- [x] 判据 2：`--full` 同时包含全部 fast 步骤与仅 full 的 sast/deps -> `tests/test_check_gate.py::test_full_selection_contains_fast_and_full_only_steps`
- [x] 判据 3：`python scripts/check.py --full` 输出 format、lint、types、test、sast、deps、secrets 共 7 步
- [x] 判据 4：stdout 格式与现有实现一致

## 反例（必须在实现前跑红）

- [x] 反例 1：调用 `select_steps(["--fast"])` -> 当前模块无该函数，`AttributeError` -> `tests/...::test_fast_selection`
- [x] 反例 2：调用 `select_steps(["--full"])` -> 同样 `AttributeError`；若只返回 full 步骤，fast 步骤缺失 -> `::test_full_selection_contains_fast_and_full_only_steps`

## 契约（如涉及对外接口）

- `select_steps(argv: list[str]) -> list`：含 `--full` 时返回 `FULL_STEPS = FAST_STEPS + [sast, deps]`，否则返回 `FAST_STEPS`

## 证据

- 反例红: `pytest tests/test_check_gate.py -q` -> `2 failed`，两条均为 `AttributeError: module 'check_gate' has no attribute 'select_steps'`
- 实现后绿: `pytest tests/test_check_gate.py -q` -> `2 passed`
