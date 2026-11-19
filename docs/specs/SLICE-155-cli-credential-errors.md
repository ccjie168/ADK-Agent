# SLICE-155 凭据配置错误的统一退出

状态: gated
依据: PROGRESS 缺口清单第 8 条：`serve-tool-gateway` 只在配置连接器时解析凭据标志，
只给 `--tools` 时忽略；`--credential-db` 与 `CREDENTIAL_DATABASE_URL` 同时给出时显式标志静默胜出，
契约文字比实现严格；工具网关、`remote-agents` 与控制台在 keyring 非法时仍打印 traceback。

## 意图

1. `serve-tool-gateway` 无论是否配置连接器都解析并校验凭据参数；只给 `--tools` 时给出
   `--credentials-dir`/`--credential-db` 退出 1 并说明需要连接器。
2. `_credential_store` 在 `--credential-db` 与 `CREDENTIAL_DATABASE_URL` 同时给出时退出 2，
   与 `--credentials-dir` 的既有冲突规则一致。
3. 工具网关、`remote-agents register|refresh` 与控制台在 keyring 非法或两个 keyring 变量
   同时设置时退出 1，错误文案同时提到两个变量名，不回显内容。
4. 契约先更新 `docs/contracts/cli.md` 的凭据后端、工具网关与 `remote-agents` 段。

## 契约（先改）

- `docs/contracts/cli.md`。

## 完成判据

- [x] 只有 `--tools` 时给凭据参数退出 1 -> `test_tool_gateway_rejects_credentials_without_connectors`
- [x] 工具网关 keyring 非法退出 1 -> `test_tool_gateway_exits_on_an_invalid_keyring`
- [x] `remote-agents` keyring 非法退出 1 -> `test_remote_agents_exit_on_an_invalid_keyring`
- [x] 控制台 keyring 非法退出 1 -> `test_console_exits_on_an_invalid_keyring`
- [x] `--credential-db` 与环境变量冲突退出 2 -> `test_credential_db_conflicts_with_the_environment`
- [x] 全量门禁通过

## 反例

- [x] 基线只有 `--tools` 时凭据参数被忽略，继续加载工具后才报无关错误
- [x] 基线工具网关、`remote-agents` 与控制台对非法 keyring 抛未捕获的 `KeyBackendError`
- [x] 基线 `--credential-db` 与环境变量并存时静默使用显式值

## 5 问威胁建模

1. **数据**：keyring、凭据库 DSN、连接器凭据。
2. **调用方**：部署这些服务的运维。
3. **信任边界**：命令行与环境变量到进程内存。
4. **恶意输入最坏结果**：误配置被静默忽略（缓解：显式拒绝）；traceback 暴露路径与环境
   （缓解：固定文案，只回显变量名与原因）。
5. **失败是否泄露信息**：不回显 keyring 或 DSN 内容。

## 范围外

- 凭据记录超过 128 字符时控制台读接口的 500（另立切片）。
- Windows 文件锁对永久错误的重试上限。
- 跨租户 admin 写入的审计归属。

## 证据

- `docs/evidence/SLICE-155-cli-credential-errors.txt`
