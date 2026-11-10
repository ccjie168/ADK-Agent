# adk-agent

## 门禁（唯一入口）

- 改完代码必须跑: `python scripts/check.py --fast`
- 声称完成前必须跑: `python scripts/check.py --full`，并贴出结果
- 唯一入口是 `scripts/check.py`，不要另起一套 lint / test 命令

## 硬规则

- 精确 `git add <文件>`，禁止 `git add -A` / `git add .`
- 改对外接口: 先改 `docs/contracts/` 契约，再改代码
- 禁止修改或删除已有测试的断言来让测试通过
- 迁移 / 删数据 / 部署 / `git tag` / `git push` / 改测试判据: 先停下来问我
- 每个切片先读 `docs/specs/SLICE-xxx.md`，先让反例测试跑红

## 目录地图

- `src/adk_agent`: 框架库（`models` / `config` / `factory` / `mcp` / `cli`）
- `tests/`: 与 `src` 镜像
- `examples/`: `minimal`、`multi_agent` 示例
- `scripts/`: `check.py`、`probe_mcp.py`、`call_tool.py`
- `docs/specs`: 切片；`docs/decisions`: ADR；`docs/evidence`: 负向验证

## 当前在做

- Phase 2: MCP `streamable-http` + 部署（待 `docs/specs/SLICE-001`）

## 项目特有禁区

- 禁止把真实 API Key 写入仓库；`.mcp.json` 只用 `${VAR}`
- 禁止把未鉴权的 MCP HTTP 端点暴露到非可信网络
- 禁止未经 ADR 新增模型通道或依赖
