# SLICE-209 触发注册接受裸 digest

状态: gated
依据: PROGRESS 已知缺口第 10 条第 3 项（`triggers register --digest` 要求 `sha256:` 前缀，注册表记录是裸 hex）。

## 意图

1. `adk-agent triggers register --digest` 同时接受 `sha256:<64 hex>` 与裸 64 位小写 hex；
   传入裸 hex 时存储统一归一化为 `sha256:<hex>`，与既有记录形状一致。
2. 其他形状（长度不对、大写、非 hex、未知前缀）仍然退出 1，提示由 pydantic 校验给出。
3. 执行服务与存储不需要改动：`triggers_service` 已用 `removeprefix("sha256:")` 读取。

## 契约（先改）

- `docs/contracts/triggers.md` 的 `digest` 条目补「注册时也接受裸 64 hex，存储统一补
  `sha256:` 前缀；执行服务与注册表记录核对时剥前缀」。

## 完成判据

- [x] 裸 hex 注册成功且存储为带前缀形状 -> `test_register_accepts_bare_digest`
- [x] 非法 digest 仍然拒绝 -> `test_register_rejects_malformed_digest`
- [x] 模型层归一化 -> `test_trigger_digest_normalizes_bare_hex`
- [x] 全量门禁通过

## 反例

- 基线 `a2ce72e`：`AgentTrigger` 的 pattern 要求 `sha256:` 前缀，裸 hex 触发 `ValidationError`，
  CLI 退出 1，`test_register_accepts_bare_digest` 与 `test_trigger_digest_normalizes_bare_hex` 失败。
- 若把校验放宽成任意字符串，`test_register_rejects_malformed_digest` 失败。

## 5 问威胁建模

1. **数据**：触发记录固定的版本 digest。
2. **调用方**：运维的 `triggers register` 命令行与脚本。
3. **信任边界**：命令行参数 → 存储记录 → 执行服务与注册表核对。
4. **恶意输入最坏结果**：错误 digest 让触发固定到别的版本或永远对不上。缓解：只接受两种精确
   形状，归一化后仍是完整 64 hex，执行服务的核对逻辑不变。
5. **失败是否泄露信息**：错误提示只含输入形状与规则，不含注册表内容。

## 范围外

- `tool-grants request --digest` 的同类易用性问题（缺口清单未列，另行切片）。
- 注册表 `publish`/`list` 输出是否补前缀。

## 证据

- `docs/evidence/SLICE-209-trigger-digest.txt`
