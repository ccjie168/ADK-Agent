# ADR-0001 项目工程基线

状态: Accepted   日期: 2026-11-10   签字: Jie CAO（工程负责人）

## 决定

1. **延迟预算**: commit <= 5s（`--fast`） / PR <= 3min / release <= 30min（`--full`）。
2. **唯一门禁入口**: `python scripts/check.py [--fast|--full] [--strict]`。
   任何绕过它的合并视为违规；CI 只调用这个入口，不另写一套逻辑。
3. **禁区**（必须人工授权，逐次）：数据库迁移 / 删数据 / deploy / `git tag` /
   `git push --force` / 修改测试判据。
4. **数据与模型通道**（CP-D1 / CP-D2）：
   - 本仓库分级：**内部（internal）**，不含生产数据与客户 PII。
   - 允许模型通道：DeepSeek 的 Anthropic 兼容端点
     （`https://api.deepseek.com/anthropic`，经 ADK `AnthropicLlm` 适配）。
     Gemini 或其它通道须另行登记后方可使用。
   - Key 托管：只放在用户级环境变量或统一网关；仓库内只允许 `${VAR}` 占位符。
   - 新增模型 / 第三方流程包：须新 ADR。

## 后果

- 本地改完代码提交前必须跑 `python scripts/check.py --fast`。
- 声称完成 / 发版前必须跑 `--full` 并把结果贴进证据。
- `.mcp.json` 只允许 `${VAR}` 展开，禁止硬编码密钥。
- 未鉴权的 MCP HTTP 端点不得暴露到非可信网络（Phase 2 必须带鉴权）。
