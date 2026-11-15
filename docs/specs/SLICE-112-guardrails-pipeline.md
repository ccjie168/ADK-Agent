# SLICE-112 输入输出护栏

状态: planned
依据: 调研记录 `docs/research/agent-framework-landscape.md`；先做内置规则，不引入新依赖。

## 意图（要什么，不写怎么写）

在模型网关与工具网关两个边界上加输入输出护栏。命中规则的输入或输出被拒绝或脱敏，决定进审计，日志不出现原文。

- 规则从 JSON 配置加载，支持正则、关键词与最长匹配长度；内置 PII 与提示注入两类规则。
- 输入命中 PII 时按规则脱敏；命中阻断规则时运行失败并返回稳定错误码。
- 输出命中时同样脱敏或阻断，再返回调用方。
- 护栏自身异常时失败即拒绝，不放行。
- 每次拦截或脱敏写一条审计事件，只记录规则 id、动作与哈希，不记录原文。

## 新增文件

- `src/adk_agent/guardrails/__init__.py`
- `src/adk_agent/guardrails/rules.py`
- `src/adk_agent/guardrails/pipeline.py`
- `tests/test_guardrails.py`

## 修改文件

- `src/adk_agent/models` 与 `src/adk_agent/tools` 的调用边界
- 配置加载与启动校验
- `docs/guides/operations.md`（规则与错误码）

## 完成判据（可执行）

- [ ] 输入命中 PII 规则后在模型调用前脱敏 -> `tests/test_guardrails.py::test_input_redaction`
- [ ] 输入命中阻断规则时返回稳定错误码并写审计 -> `::test_input_blocked`
- [ ] 输出命中规则时脱敏或阻断后再返回 -> `::test_output_guard`
- [ ] 规则停用时原样通过 -> `::test_disabled_rule_passes`
- [ ] 配置非法时启动失败 -> `::test_invalid_config_fails_startup`
- [ ] 护栏异常时失败即拒绝 -> `::test_pipeline_error_fails_closed`
- [ ] 审计与日志不含命中原文 -> `::test_no_raw_value_logged`

## 反例（必须在实现前跑红）

- [ ] 反例 1：规则停用后仍被拦截 -> 期望 `::test_disabled_rule_passes` 失败
- [ ] 反例 2：大小写或空白变体绕过关键词 -> 期望阻断测试失败
- [ ] 反例 3：护栏抛错时请求被放行 -> 期望 `::test_pipeline_error_fails_closed` 失败
- [ ] 反例 4：审计里出现命中原文 -> 期望 `::test_no_raw_value_logged` 失败

## 契约（如涉及对外接口）

不新增平台 API。新增稳定错误码与规则配置格式，写进运维手册；若对外暴露配置接口，先补契约。

## 5 问威胁建模（10 分钟）

1. **数据**：用户输入、模型输出、工具参数与结果、规则配置。
2. **调用方**：控制台、MCP、A2A、模型网关、工具网关。
3. **信任边界**：用户输入到模型；模型输出到用户；工具参数到外部系统。
4. **恶意输入最坏结果**：绕过规则泄露 PII（缓解：归一化、大小写与空白处理、组合规则）；规则误伤正常请求（缓解：规则分级与试运行）；护栏异常放行（缓解：失败即拒绝）；审计泄露原文（缓解：只存哈希与规则 id）。
5. **失败是否泄露信息**：错误码固定，不返回命中的原文、规则内部正则或文件路径。

## 范围外

- 引入 Presidio 或外部内容审核服务。需要时单独立 ADR。
- 模型级红队与评测。那是 SLICE-110 之后的评测工作。
- 对历史数据做回溯清洗。

## 证据

- 反例红: 待实现
- 实现后绿: 待实现
