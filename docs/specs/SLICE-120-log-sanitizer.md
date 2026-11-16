# SLICE-120 日志注入过滤

状态: gated
依据: ADR-0022 批次 CodeQL 审核发现 29 条 `py/log-injection`，按 2027-01-31 接受。租户名、agent 名或请求目标含换行时，日志可以伪造出额外的行。需要在记录层集中转义，而不是逐处修改 29 个调用点。

## 意图（要什么，不写怎么写）

新增中央日志清洗器，在记录进入任何 handler 之前把 CR 与 LF 转成字面 `\r` 与 `\n`。

- 用 `logging.setLogRecordFactory` 包装现有工厂，覆盖所有 logger，不依赖 uvicorn 的 handler 配置。
- 清洗 `record.msg`、tuple 形式的 `record.args` 与 dict 形式参数中的字符串。非字符串参数保持原样，`%d` 等格式化不受影响。
- 安装幂等。重复调用不会二次转义。
- 在 `build_console_app` 入口安装，控制台启动即生效。

## 数据形状

`src/adk_agent/logsafe.py`：

- `install_log_sanitizer() -> None`：全局安装一次。
- 内部工厂类包装原工厂，对每条记录做字符串清洗。
- 模块级已安装标记，保证幂等。

清洗规则固定为两个替换。`\r` 转成两个字符 `\r`，`\n` 转成两个字符 `\n`。不做其他转义，不改变普通消息。

## 新增文件

- `src/adk_agent/logsafe.py`
- `tests/test_log_sanitizer.py`
- `docs/evidence/SLICE-120-log-sanitizer.txt`

## 修改文件

- `src/adk_agent/console.py`（入口安装）
- `docs/specs/ROADMAP.md`
- `docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 消息中的换行被转义 -> `tests/test_log_sanitizer.py::test_message_newlines_are_escaped`
- [x] 参数中的换行与回车被转义 -> `::test_argument_newlines_are_escaped`
- [x] dict 参数中的换行被转义 -> `::test_mapping_arguments_are_escaped`
- [x] 普通消息与数字参数不变 -> `::test_normal_messages_are_unchanged`
- [x] 重复安装不会二次转义 -> `::test_install_is_idempotent`
- [x] 构建控制台后清洗器已生效 -> `::test_console_installs_sanitizer`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：没有清洗器，含换行的值在日志里形成两行 -> 期望 `::test_argument_newlines_are_escaped` 失败
- [x] 反例 2：重复安装把 `\n` 二次转义成 `\\n` -> 期望 `::test_install_is_idempotent` 失败
- [x] 反例 3：清洗器把数字参数当字符串，破坏 `%d` -> 期望 `::test_normal_messages_are_unchanged` 失败

红态记录: 实现前 `pytest tests/test_log_sanitizer.py -q` 以 1 error 失败，报 `ModuleNotFoundError: No module named 'adk_agent.logsafe'`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户名、agent 名、请求目标、错误码等进入日志的字符串。
2. **调用方**：控制台进程内的所有 logger。
3. **信任边界**：请求数据到日志文件或聚合器。
4. **恶意输入最坏结果**：换行使攻击者伪造日志行，误导排障或审计对照（缓解：记录工厂统一转义 CR/LF）；清洗破坏格式化（缓解：只动字符串参数，数字保持原样）；重复安装导致双重转义（缓解：模块级幂等标记）。
5. **失败是否泄露信息**：清洗器不增加字段、不改变正常消息，不引入新泄露面。

## 范围外

- 结构化日志或日志聚合器改造。
- 其他服务的日志安装。模块可复用，本切片只接控制台。
- 修改 29 个调用点。集中清洗优先。
- CodeQL 告警的重新打开或策略调整。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-120-log-sanitizer.txt`
- ADR-0022 的 29 条 `py/log-injection` 接受风险由本切片收敛，重扫后保持 dismissed。
