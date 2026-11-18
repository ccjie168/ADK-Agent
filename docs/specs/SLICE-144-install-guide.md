# SLICE-144 稳定的安装与使用手册

状态: gated
依据: `docs/PROGRESS.md` 的下一刀清单。README 是项目介绍加快速开始，`operations.md` 是多副本运维，缺一份面向首次部署的安装与使用手册。

## 意图

1. 新增 `docs/guides/install-and-use.md`：前提、从源码安装、模型配置、MCP/控制台、
   发布与加载、服务面参数表、凭据（写入/控制面/轮换/吊销）、Docker、升级回滚、排障。
2. 手册里出现的每个 `-m adk_agent <cmd>` 都必须是真的子命令；用测试锁定。
3. 多副本、备份与密钥轮换细节仍指向 `operations.md`，不重复。

## 契约（先改）

- 无对外接口变化；这是文档切片。

## 完成判据

- [x] 手册包含安装、模型、控制台、发布、凭据、Docker、升级与排障 -> `test_guide_covers_the_required_sections`
- [x] 手册里的命令都是真实子命令 -> `test_every_guide_command_is_a_real_subcommand`
- [x] 手册里每个 flag 都被对应命令接受 -> `test_every_guide_flag_is_accepted_by_its_command`
- [x] `compose` 与 `publish` 示例带齐必填 flag -> `test_guide_commands_carry_the_required_flags`
- [x] 手册写明 `ADK_SECRET_KEKS`、`credentials rewrap` 与控制面 TLS 要求 -> `test_guide_names_the_credential_environment`
- [x] 全量门禁通过

## 反例

- [x] 基线没有 `install-and-use.md`，新用例在基线上文件不存在失败
- [x] 手册写一个不存在的命令（如 `adk_agent deploy`）会让命令用例失败

## 5 问威胁建模

1. **数据**：手册包含命令与配置，不含真实密钥。
2. **调用方**：首次部署的开发者与运维。
3. **信任边界**：无；文档不执行。
4. **恶意输入最坏结果**：无（示例里只有 `${VAR}` 占位符，没有 API Key）。
5. **失败是否泄露信息**：不适用；示例密钥一律用占位符。

## 范围外

- 首次真实发布与 `git tag`（需要单独确认）。
- 手册的英文版本。
- 截图与录屏。

## 证据

- `docs/evidence/SLICE-144-install-guide.txt`
