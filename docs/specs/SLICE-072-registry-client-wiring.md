# SLICE-072 控制台、MCP 与发布命令接注册表服务

状态: merged
依据: ADR-0009 第 5 条，`docs/contracts/cli.md`，SLICE-071。

## 意图（要什么，不写怎么写）

注册表控制面已经能跑，但命令还只认本地目录。这一刀把 `--registry-url URL` 与 `--registry-token-env VAR` 接进 `console`、`serve`、`serve-many` 和 `publish`，让多副本看到同一份目录。

- 给了 URL 时元数据走 `HttpAgentRegistry`，忽略 `--registry DIR`；token 只从环境变量读，默认 `ADK_REGISTRY_AUTH_TOKEN`。
- `console`、`serve`、`serve-many` 的运行工件仍从 `--artifact-dir` 或 `$ARTIFACT_URL` 读取，可信公钥仍为必需。
- `publish --registry-url` 先 `POST /v1/agents`；带 `--artifact` 时再 `PUT /v1/artifacts/{digest}`。此模式下 `--artifact-dir` 和 `$ARTIFACT_URL` 不参与，同时给退出 1。
- 市场页不需要单独改：`/api/registry` 读的是传入的注册表对象，换成 HTTP 客户端即可跨副本。
- `publish --registry-url` 拒绝 `--eval-report`：评测报告还没有集中存储，写本地目录会造成假象。
- 文件注册表保留，作为单机演示。

## 新增文件

- `tests/test_registry_url_wiring.py`
- `docs/evidence/SLICE-072-registry-client-wiring.txt`

## 修改文件

- `src/adk_agent/cli.py`：`_agent_registry` 辅助函数与四条命令接线
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
_agent_registry(args) -> FileAgentRegistry | HttpAgentRegistry
  args.registry_url 有值 -> HttpAgentRegistry(url, auth_token=$<registry-token-env>)
  否则                    -> FileAgentRegistry(args.registry)
```

## 完成判据（可执行）

- [x] 有 URL 时返回 HTTP 客户端 -> `tests/test_registry_url_wiring.py::test_agent_registry_prefers_url`
- [x] 无 URL 时仍是文件实现 -> `::test_agent_registry_falls_back_to_files`
- [x] 非 http(s) URL 退出 1 -> `::test_bad_url_rejected`
- [x] 控制台把客户端交给 `run_console` -> `::test_console_wires_http_registry`
- [x] `serve` 从 HTTP 注册表解析引用 -> `::test_serve_uses_http_registry`
- [x] 发布走 HTTP 并打印摘要 -> `::test_publish_uses_http_registry`
- [x] 发布会把工件字节 PUT 上去 -> `::test_publish_uploads_artifact`
- [x] 发布时本地工件目录与服务 URL 互斥 -> `::test_publish_artifact_source_exclusive`
- [x] 发布时 `--eval-report` 与服务 URL 互斥 -> `::test_publish_eval_report_exclusive`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`console --registry-url ...` -> 当前 argparse 退出 2
- [x] 反例 2：`publish --registry-url ...` -> 当前 argparse 退出 2
- [x] 反例 3：`ftp://` URL 被接受 -> 当前参数不存在，无此行为

## 契约（如涉及对外接口）

契约已在 SLICE-071 先改：`docs/contracts/cli.md` 的「客户端 `--registry-url`」一节。

## 5 问威胁建模（10 分钟）

1. **数据**：注册表 URL、token、manifest、工件字节。
2. **调用方**：运维和开发者命令行。
3. **信任边界**：命令进程到注册表服务；token 环境变量。
4. **恶意输入最坏结果**：明文 HTTP 泄露 token（缓解：文档要求回环或 TLS 终止；token 不上命令行）；错误 URL 连到任意主机（缓解：只接受 http(s)，由使用者负责网络边界）；发布到错误租户（缓解：服务端 OIDC 租户绑定）。
5. **失败是否泄露信息**：客户端只报服务状态与错误码，不回显 token。

## 范围外

- 控制台 UI 的远程发布入口。
- 按需加载未启动的版本。
- 服务端 RLS 与生命周期。

## 证据

- 反例红: `docs/evidence/SLICE-072-registry-client-wiring.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真服务 + 真控制台 + 真发布命令
