# SLICE-287 compose 签名密钥运维手册

状态: gated
依据: ADR-0043 的后续项（密钥托管、轮换与最小权限）；PROGRESS 第 16 条的「可选 SLICE-282」

## 意图

页面一键发布已经上线，但运维没有一份可执行的密钥手册：怎么生成两把 Ed25519 私钥、怎么配
`console` 的四个 `--compose-*` 参数、读取端与注册表需要哪些公钥、怎么轮换、泄露时怎么撤销。
本切片新增 `docs/guides/compose-signing.md`，并在 `docs/guides/operations.md` 的「密钥轮换」里
链接它。

只写可执行、与实际代码一致的步骤：

- 用 `openssl genpkey -algorithm ed25519` 生成私钥，`chmod 600`，用 Python 片段导出 32 字节公钥的 hex；
- 四个参数 all-or-none，只从文件读 PEM；缺全部时 `POST /api/compose` 404 `compose_not_configured`；
- 读取端（控制台/MCP/serve）用 `--artifact-keys` 或 `ADK_ARTIFACT_KEYS` 信任发布密钥；
  HTTP 注册表用 `--builder-keys` 或 `ADK_BUILDER_KEYS` 校验构建签名；
- 轮换是加法：先加新公钥到信任集并滚动读取端，再切换控制台私钥，旧公钥留到旧版本退役；
- 泄露处置：先停用控制台参数，再吊销公钥，最后用 `agent.compose` 审计排查；
- 最小权限：两把私钥与审计 keyring、凭据 KEK 分离，不进口令、环境变量、镜像或仓库；
- 已知限制：文件注册表不校验构建签名；模板只有 `single-llm`；审计不记录指令原文。

## 契约（先改）

无接口变化；`docs/contracts/cli.md` 已描述四个参数，本切片只引用。

## 完成判据

- [ ] 手册覆盖生成与四个参数 -> `test_guide_covers_generation_and_flags`
- [ ] 手册覆盖信任集、轮换、撤销与审计 -> `test_guide_covers_trust_rotation_and_revocation`
- [ ] 运维手册链接到该指南 -> `test_operations_links_the_guide`

## 反例

实现前指南文件不存在，三条用例失败（读文件即失败）。

## 5 问威胁建模

1. **数据**：私钥文件路径与公钥 hex；手册不包含任何真实密钥值。
2. **调用方**：控制台运维与值班人员。
3. **信任边界**：私钥只落在控制台主机；信任集是公开信息。
4. **恶意输入**：无运行时输入；示例命令只用文件路径与环境变量名。
5. **失败是否泄露信息**：口令与 DSN 不回显；泄露处置要求先停用端点再吊销。

## 范围外

- 自动轮换、KMS/HSM 托管。
- 文件注册表的构建签名校验（记录为已知限制）。

## 证据

- `docs/evidence/SLICE-287-compose-key-runbook.txt`
