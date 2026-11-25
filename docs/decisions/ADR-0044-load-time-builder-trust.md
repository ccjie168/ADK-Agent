# ADR-0044 载入侧校验构建签名

状态: Accepted   日期: 2026-11-25   签字: Jie CAO（会话确认，见文末）

## 背景

`in_process` 工件会在平台进程内执行 Python，构建签名（builder signature）是它唯一的准入凭据：
发布签名证明「谁发布的」，构建签名证明「这段代码来自平台构建路径」。目前只有两个写入口校验它：

- `serve-registry` 的 `POST /v1/agents`：`in_process` 记录带工件时必须能用 `--builder-keys`
  验证构建签名，否则 503 `builder_key_unavailable` 或 400 `artifact_untrusted`。
- CLI `publish` / `compose`：写本地或 HTTP 注册表前，`in_process` 工件要求
  `--builder-keys`/`ADK_BUILDER_KEYS` 并验证。

读取侧没有同样的检查。`load_agent` 只验证发布签名（`TrustStore.verify`），随后直接执行
`in_process` 工件。后果：

- 持有发布私钥、但没有构建私钥的主体，绕过 CLI 直接写文件注册表的 JSON（文件注册表只是目录），
  或者让一个被攻陷的 HTTP 注册表返回记录，就能让未经平台构建签名的代码在进程内执行。
- CLI `publish` 的自查发生在写入之前，对已经落盘的记录与第三方写入的记录无效。

SLICE-287 的运维手册与 PROGRESS 都记录了这条限制「文件注册表不校验构建签名」，本次把它收口。

## 决定

### 1. 载入时按执行层级校验

`load_agent` 新增可选参数 `builder_keys: TrustStore | None`，在发布签名验证之后：

- `manifest.execution_tier == "sandboxed"`：不要求构建签名，与 `serve-registry` 一致。
- 其余（`in_process` 与历史缺失字段的记录，均按 `in_process` 读取）：必须提供 `builder_keys`
  并通过 `verify_builder`。缺失信任集或验证失败都拒绝载入，错误信息写明原因，
  CLI 以退出码 1 结束。

这层检查与注册表类型无关：文件注册表与 HTTP 注册表都经过同一段载入代码，因此对前者是补齐缺口，
对后者是纵深防御（注册表被攻陷时仍需要构建私钥）。

### 2. 四个载入入口新增 `--builder-keys`

`serve`、`serve-many`、`serve-a2a`、`console` 的 `--agent-ref` 路径新增 `--builder-keys FILE`
（回退环境变量 `ADK_BUILDER_KEYS`），沿用已有的 `TrustStore.from_json` 校验：JSON 对象、
键名为非空字符串、值为 64 位十六进制。

- 只在真正载入 `in_process` 工件时强制；只载入 `sandboxed` 记录的环境不需要该参数，
  行为不变。
- 不新增代码依赖，复用 `registry/trust.py` 与 `registry/signing.py`。
- 参数名、环境变量与 `serve-registry`、CLI `publish` 完全一致，运维只需要一套信任集文件。

### 3. 兼容性与迁移

- 载入 `in_process` 工件却未配置构建信任集时，**从静默执行变为显式失败**。这是有意的收紧：
  默认放行等于把缺口留在原地。
- 受影响部署：用 `--agent-ref` 载入 `in_process` 工件的 `serve*`/`console`。迁移方式是把现有
  `--builder-keys` 信任集（或 `ADK_BUILDER_KEYS`）加到启动参数；手册与契约写明报错文案。
- 只载入 `sandboxed` 记录、或不使用 `--agent-ref` 的部署不受影响。

### 4. 契约

- `docs/contracts/cli.md`：四个命令的用法行与说明补 `--builder-keys`；写明
  「载入 `in_process` 工件时必须提供，缺失退出 1」与 `ADK_BUILDER_KEYS` 回退。
- `docs/contracts/registry_service.md`：补一句读取侧同规则，声明写入口的校验不是唯一防线。
- `docs/guides/install-and-use.md`、`docs/guides/compose-signing.md`、`docs/guides/operations.md`：
  删掉「文件注册表不校验构建签名」的说明，改为「载入侧统一校验」与迁移步骤。

## 切片

- SLICE-291：`load_agent`/`load_registry_agents` 增加 `builder_keys`，四个 CLI 入口接线，
  契约先改，反例测试（手写文件注册表记录 + 未受信构建签名在 master 上可载入、修复后拒绝），
  门禁与证据。
- SLICE-292：三份运维/使用手册与 PROGRESS 收口，`compose-signing.md` 的残余限制段删改。

## 备选与否决

- **只在配置了 `--builder-keys` 时校验**：配置文件就是绕过开关，缺口原样保留。否决。
- **只在文件注册表校验**：HTTP 注册表被攻陷的路径仍然可执行未构建签名的代码；载入代码是同一段，
  分开写反而增加分支。否决。
- **把校验放在 `FileAgentRegistry.get/list`**：注册表存储层拿不到信任集，也会让测试替身与
  只读工具被迫携带信任；放在载入边界更贴合「执行前最后一道门」。否决。
- **要求所有记录（含 `sandboxed`）都有构建签名**：与 `serve-registry` 的现行契约不一致，
  而沙箱执行的信任模型不同（沙箱内运行，不是进程内）。超出本次范围。否决。

## 后果

- 任意写入路径（CLI、控制台、手工文件、被攻陷的注册表）都要过同一道载入校验，
  `in_process` 的执行准入收敛为「发布签名 + 构建签名」两个独立密钥。
- 运维多一个必填参数（仅 `in_process` 载入场景），复用现有信任集文件，无新依赖。
- 构建密钥轮换需要在所有载入端同步更新信任集；手册已描述轮换顺序，补上载入端清单。

## 风险

- 载入端的严格校验可能让原本「能跑」的旧部署启动失败；这是显式失败，报错文案会指出缺失参数。
- 信任集文件本身若被替换，校验形同虚设；该文件与 `--artifact-keys` 同级，同属部署信任根，
  由主机文件权限保护，不在本 ADR 扩展范围。

## 确认记录

- 2026-11-25：用户从缺口清单中选择「文件注册表校验构建签名」作为下一项。
- 2026-11-25：用户确认采用「严格失败」方案：载入 `in_process` 工件必须有构建信任集，
  缺失即退出 1；接受受影响部署需要补 `--builder-keys` 的行为变化。
