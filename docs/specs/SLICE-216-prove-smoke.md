# SLICE-216 验收脚本的发布冒烟子集

状态: gated
依据: 2026-11-21 复盘第七节第 4 条（给 `prove_it_works.py` 加 `--smoke` 子集作发布前检查）。

## 意图

1. `scripts/prove_it_works.py` 新增 `--smoke`，只跑 P1–P4（环境、审计链、发布/加载/对话、工具网关），
   作为发布前检查；完整 12 项留给验收环境。
2. `--smoke` 与 `--only` 互斥，argparse 直接拒绝（退出 2）。
3. 选择逻辑抽成纯函数 `select_checks(only, smoke)`，不启动容器就能验证。

## 契约（先改）

- 脚本的 `--help` 就是操作接口；模块 docstring 的用法段先补 `--smoke`。

## 完成判据

- [x] `--smoke` 选中 P1–P4 -> `test_smoke_selects_the_release_subset`
- [x] `--only` 仍然按逗号切分并去空白 -> `test_only_is_split_and_trimmed`
- [x] 默认仍是 12 项 -> `test_default_runs_every_check`
- [x] `--smoke` 与 `--only` 互斥 -> `test_smoke_and_only_are_mutually_exclusive`
- [x] 全量门禁通过

## 反例

- 基线 `646d0f7`：没有 `select_checks`、`CHECKS`、`build_parser`，五个用例全部 `AttributeError`。
- 若只把 `--smoke` 当成普通参数，互斥用例不会退出 2。

## 5 问威胁建模

1. **数据**：验收检查的选择。
2. **调用方**：发布负责人。
3. **信任边界**：命令行参数 → 启动哪些真实进程与容器。
4. **恶意输入最坏结果**：参数组合让发布检查悄悄只跑一两项，误以为全绿。缓解：`--smoke` 的子集是
   固定常量并有用例锁定；未知 id 仍按原逻辑记为失败。
5. **失败是否泄露信息**：只影响选择，不输出凭据。

## 范围外

- 把 `--smoke` 接进 CI 或发布流水线。
- 调整 P1–P4 的内容。

## 证据

- `docs/evidence/SLICE-216-prove-smoke.txt`
