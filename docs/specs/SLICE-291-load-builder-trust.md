# SLICE-291 载入侧校验构建签名

状态: active
依据: ADR-0044（载入侧校验构建签名，2026-11-25 已确认）

## 意图

`in_process` 工件在平台进程内执行，构建签名是准入凭据。写入口（`serve-registry` 的
`POST /v1/agents`、CLI `publish`/`compose`）已经校验，载入侧（`load_agent`）只验证发布签名。
本切片让载入侧对 `in_process` 与历史无层级记录强制构建签名：缺少可信构建公钥或验签失败都拒绝
执行。`sandboxed` 记录保持现状（沙箱内执行，与 `serve-registry` 的契约一致）。

## 契约（先改）

- `docs/contracts/cli.md`「从注册表启动」一节：四个命令新增 `--builder-keys FILE`（或
  `ADK_BUILDER_KEYS`），载入 `in_process` 工件时必需，缺失或验签失败退出 1；`serve`、
  `serve-many`、`serve-a2a`、`console` 的用法行同步补参数。
- `docs/contracts/registry_service.md`：补一句读取侧按同一规则校验，写入口的检查不是唯一防线。
- `docs/contracts/console.md` 的 `/api/registry/load` 一节：`in_process` 记录要求构建信任集，
  缺少返回 503 `builder_trust_unavailable`，验证失败返回 409 `artifact_untrusted`；
  `--builder-keys` 加入控制台参数表。
- `docs/guides/install-and-use.md`、`docs/guides/compose-signing.md`：去掉「文件注册表不校验
  构建签名」的说明，写清迁移方式（给载入端加 `--builder-keys`）。
- 本切片的 `docs/guides/operations.md` 收口放到 SLICE-292。

## 完成判据

- [ ] 无构建信任集时拒绝载入 `in_process` 工件 -> `test_load_rejects_an_in_process_artifact_without_builder_trust`
- [ ] 构建签名来自未受信密钥时拒绝载入 -> `test_load_rejects_an_untrusted_builder_signature`
- [ ] 受信构建签名正常载入 -> `test_load_accepts_a_trusted_builder_signature`
- [ ] `sandboxed` 记录不要求构建信任集 -> `test_load_does_not_require_builder_trust_for_sandboxed`
- [ ] `console --agent-ref` 载入 `in_process` 记录缺 `--builder-keys` 时退出 1
  -> `test_console_refuses_in_process_without_builder_keys`
- [ ] 未受信构建公钥让 `console --agent-ref` 退出 1 -> `test_console_refuses_an_untrusted_builder_key`
- [ ] `serve --agent-ref` 带 `--builder-keys` 可载入 -> `test_serve_accepts_builder_keys`
- [ ] 控制台按需载入接口缺构建信任集时返回 503 且不载入 -> `test_registry_load_requires_builder_trust`
- [ ] 控制台按需载入接口有受信构建公钥时载入 -> `test_registry_load_accepts_builder_trust`
- [ ] 未受信构建公钥让控制台按需载入返回 409 -> `test_registry_load_rejects_an_untrusted_builder`
- [ ] `--full` 门禁通过

## 反例

先手写一条文件注册表记录（发布签名域内、构建签名缺失），在 master 上 `load_agent` 会执行
`in_process` 工件并返回 agent；新增用例在 master 上失败（无异常）。CLI 用例在 master 上退出 0
或只因未知参数退出 2，修复后退出 1 且 stderr 指明缺少 `--builder-keys`。

## 5 问威胁建模

1. **数据**：已发布记录的构建签名与构建公钥信任集；不含私钥。
2. **调用方**：启动 `console`/`serve*` 的运维，以及写入文件注册表或控制注册表服务的任意主体。
3. **信任边界**：信任集文件是部署信任根；载入进程内代码是执行边界，必须在执行前校验。
4. **恶意输入**：篡改记录、伪造构建签名、未受信 key id、非法信任集文件；错误码与退出码固定，
   不执行工件字节。
5. **失败是否泄露信息**：失败信息只包含缺失参数或「构建签名不可信」，不回显密钥材料。

## 范围外

- `sandboxed` 工件要求构建签名（与 `serve-registry` 契约不一致，另行评估）。
- 构建密钥轮换工具与信任集分发。
- 控制台页面发布路径的改动（`POST /api/compose` 已用构建私钥签名）。

## 证据

- `docs/evidence/SLICE-291-load-builder-trust.txt`
