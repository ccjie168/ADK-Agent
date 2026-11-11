# SLICE-007 配置化 thinking budget

状态: merged

## 意图（要什么，不写怎么写）

配置驱动的 agent 需要控制模型 thinking。`ModelConfig.thinking_budget` 非空时，
`build_agent` 向 `LlmAgent` 传入对应的 `GenerateContentConfig`；未设置时保持
`generate_content_config is None`，不改变默认行为。`examples/minimal/framework.json`
显式设为 0，兼容 DeepSeek 多轮。

## 完成判据（可执行）

- [x] 判据 1：`thinking_budget: 0` 的配置构建出的 agent，`generate_content_config.thinking_config.thinking_budget == 0` -> `tests/test_config_thinking.py::test_thinking_budget_is_applied`
- [x] 判据 2：未设置 `thinking_budget` 时 `agent.generate_content_config is None` -> `::test_no_thinking_budget_leaves_generate_content_config_unset`
- [x] 判据 3：`examples/minimal/framework.json` 的 model 含 `"thinking_budget": 0`

## 反例（必须在实现前跑红）

- [x] 反例 1：`ModelConfig(thinking_budget=0)` -> 字段不存在时被静默丢弃，`build_agent` 产出 `generate_content_config=None`，断言 `AttributeError: 'NoneType' object has no attribute 'thinking_config'`

## 契约（如涉及对外接口）

- `ModelConfig.thinking_budget: int | None = None`
- `build_agent`：非 None 时传 `types.GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_budget=...))`；None 时不传该关键字（ADK 收到 `None` 会实例化默认配置）

## 5 问威胁建模（10 分钟）

1. **数据**：模型调用参数。
2. **调用方**：读取 `framework.json` 的 CLI 与示例。
3. **信任边界**：配置文件进入构建器。
4. **恶意输入最坏结果**：非整数 budget -> pydantic 类型校验拒绝。
5. **失败是否泄露信息**：配置错误直接抛出，不包含密钥。

## 证据

- 反例红: `pytest tests/test_config_thinking.py -q` -> `1 failed, 1 passed`，`AttributeError: 'NoneType' object has no attribute 'thinking_config'`
- 实现后绿: `pytest tests/test_config_thinking.py -q` -> `2 passed`
