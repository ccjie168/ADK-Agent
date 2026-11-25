# 切片检查表

`CLAUDE.md` 规定切片怎么走；这一页是每一步的检查点，以及哪些检查已经被脚本或测试固化。
能写成一个会失败的检查，就不要只写成一句提醒。

## 顺序

1. 读 `docs/PROGRESS.md` 的缺口清单与 `docs/specs/SLICE-xxx.md`。
2. 对外接口有变化时，先改 `docs/contracts/`。
3. 先写反例测试并跑红；写不出红态时，在 spec 里说明原因，不要写一个基线就绿的用例。
4. 实现最小改动。
5. `python scripts/check.py --fast`。
6. `python scripts/check.py --full`，保留输出尾巴。
7. 精确 `git add <文件>`，提交、推送、开 PR。
8. 独立只读验证代理复核 diff、证据与 `--full`。
9. 修完再验，squash merge，然后只发一条汇总，更新 PROGRESS 与交接记忆。

## 已被自动化固化的检查

| 检查 | 位置 |
| --- | --- |
| 活跃 spec 有意图、判据、反例、威胁建模、证据 | `scripts/check_specs.py` |
| spec 引用的 `test_*` 必须真实存在于 `tests/`（裸名、`test_x()`、`path::test_x` 都校验；SLICE-146 起） | `scripts/check_specs.py`、`tests/test_check_specs.py` |
| 门禁唯一入口与步骤集合 | `scripts/check.py`、`tests/test_check_gate.py` |
| 安装手册里的命令与 flag 真实可执行 | `tests/test_install_guide.py` |
| 发布说明与 `pyproject.toml` 版本一致、无占位 | `tests/test_release_notes.py` |
| 部署清单与运维手册章节 | `tests/test_deploy_manifests.py` |
| 验收脚本的每个服务调用同时带 `--artifact-keys` 与 `--builder-keys` | `tests/test_prove_harness_builder_trust.py` |

## 提交前人工检查

- 证据与发布说明里的数字来自**最后一次**运行，不是更早的提交。
- spec 里的用例名逐个存在；`check_specs.py` 会拦，但先自己看一遍。
- 文档切片的每个代码块能在干净检出上按顺序执行；需要文件的地方，前面的块要负责创建它。
- 新上限/不变量要测到精确边界值（例如恰好 128 字符），不只测越界。
- 接触 CLI flag 的测试清掉宿主环境变量（`CREDENTIAL_DATABASE_URL`、`ADK_SECRET_KEKS`）。
- 并发结论要有强制交错的用例，不是“先 disable 再 rewrap”的顺序用例。
- 没有 `git add -A` / `git add .`；没有改已有测试的断言（只改输入数据要在证据里写明）。
- 收紧载入或执行契约（新增必需参数、加校验、改默认拒绝方向）时，grep 所有消费端：
  `src/` 调用点、`scripts/prove_it_works.py`、`scripts/demo_seed.py`、测试与手册。
  验收与演示脚本要同步补参数，并加静态锁定测试，不能只靠人记得。
  SLICE-291 加严构建签名后，验收脚本六处服务调用漏了 `--builder-keys`，
  端到端验收因此 6 项失败（SLICE-295 修复）。

## 工具约定

- 中文与转义多的内容用 Write/Edit，不要用 bash heredoc（会把 `\n`、`\b` 写坏）。
- `ruff format` 只对改过的 Python 文件运行；对 `docs/` 运行会重排 Markdown 里的代码块。
- 测试目录不要命名为 `mcp` 或 `secrets`。

## 停下来问的情况

ADR 待确认；迁移、删数据、部署、`git tag`；改测试判据；新依赖或新模型通道；新的安全风险接受；
缺口清单为空；用户明确说停。
