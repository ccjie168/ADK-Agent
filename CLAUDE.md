# adk-agent

## 门禁（唯一入口）

- 改完代码必须跑: `python scripts/check.py --fast`
- 声称完成前必须跑: `python scripts/check.py --full`，并贴出结果
- 唯一入口是 `scripts/check.py`，不要另起一套 lint / test 命令

## 切片自动流程

- 接受 ADR 后按缺口清单连续执行切片，不等人工确认。一个切片合并、发汇总、更新 PROGRESS 与交接记忆之后，同一回合内立即选下一项开工。汇总不是等待信号。
- 只有以下情况停下来问我: ADR 待确认；迁移、删数据、部署、`git tag`、改测试判据、新依赖或新模型通道、新的安全风险接受；缺口清单为空；我明确说停。
- 不为“接下来做哪个”发问。缺口清单有多项时按 PROGRESS 顺序取第一项；顺序明显不合理时先做再在汇总里说明理由。
- 每个切片从 spec 到合并不再逐次确认: 写 spec 与契约、先红后绿、跑门禁、push、开 PR、按 ADR-0023 分诊告警、全绿且可合并时 squash merge。
- 合并前必须有一个独立只读验证代理确认 diff、证据与 `--full` 结果，不采信实现代理的自述。验证不通过就修，修完再验，不打断自动化。
- 每个切片只发一条汇总，含 PR 链接、门禁数字与证据路径。
- 每个切片按 `docs/guides/slice-checklist.md` 的检查点执行；spec 引用的用例名由 `scripts/check_specs.py` 校验必须真实存在。

## 硬规则

- 精确 `git add <文件>`，禁止 `git add -A` / `git add .`
- 改对外接口: 先改 `docs/contracts/` 契约，再改代码
- 禁止修改或删除已有测试的断言来让测试通过
- 迁移 / 删数据 / 部署 / `git tag` / 改测试判据 / 新依赖或新模型通道 / 新的安全风险接受: 先停下来问我
- ADR 需要我确认后才能进入实现
- 每个切片先读 `docs/specs/SLICE-xxx.md`，先让反例测试跑红

## 目录地图

- `src/adk_agent`: 框架库（`core` 契约与端口、`models` 模型网关、`tools` 工具网关/守卫/沙箱、`secretstore` 密钥、`registry` 注册表、`runtime` 运行时、`orchestration` 计划执行器、`console` 控制台、`mcp`、`cli`）
- `tests/`: 与 `src` 镜像
- `examples/`: `minimal`、`multi_agent` 示例
- `scripts/`: `check.py`、`probe_mcp.py`、`call_tool.py`
- `docs/specs`: 切片；`docs/decisions`: ADR；`docs/evidence`: 负向验证

## 当前在做

- M0 到 M5 已完成，最新切片 SLICE-133（控制台读接口能力校验）。下一步按 `docs/PROGRESS.md` 的缺口清单选，当前是控制台、A2A 与 `--agent-ref` 的沙箱执行适配。

## 项目特有禁区

- 禁止把真实 API Key 写入仓库；`.mcp.json` 只用 `${VAR}`
- 禁止把未鉴权的 MCP HTTP 端点暴露到非可信网络
- 禁止未经 ADR 新增模型通道或依赖
- 测试目录不要命名为 `mcp` 或 `secrets`。前者干扰 ruff 的 import 分类，后者命中读取禁区。密钥包名用 `secretstore`
