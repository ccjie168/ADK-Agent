# SLICE-NNN <标题>

状态: draft | planned | in_progress | review | gated | merged

## 意图（要什么，不写怎么写）

...

## 完成判据（可执行）

- [ ] 判据 1 -> 对应测试 `tests/test_xxx.py::test_ok`

## 反例（必须在实现前跑红）

- [ ] 反例 1: <非法输入 / 边界> -> 期望 <拒绝 / 报错> -> `tests/...::test_reject`

## 契约（如涉及对外接口）

- schema: `docs/contracts/xxx.json`

## 5 问威胁建模（10 分钟）

1. 数据：涉及哪些数据？
2. 调用方：谁会调用？
3. 信任边界：哪里跨信任边界？
4. 恶意输入最坏结果（-> 写成反例测试）
5. 失败是否泄露信息

## 证据

- 反例红: <贴输出>
- 实现后绿: <贴 `check --full` 输出>
