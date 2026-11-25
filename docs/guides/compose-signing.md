# 页面一键发布的签名密钥

依据：ADR-0043。控制台的 `POST /api/compose` 用两把 Ed25519 私钥给 `single-llm` 模板生成的
`in_process` 工件签名；私钥只在服务端内存里，页面从不下发或接收私钥。

## 生成密钥

两把密钥分开生成，分别用于发布签名与构建签名：

```bash
umask 077
openssl genpkey -algorithm ed25519 -out compose.pem
openssl genpkey -algorithm ed25519 -out compose-builder.pem
chmod 600 compose.pem compose-builder.pem
```

导出公钥的 32 字节 raw hex（写进信任集用）：

```bash
python - <<'PY'
from cryptography.hazmat.primitives import serialization
from pathlib import Path

for name in ("compose.pem", "compose-builder.pem"):
    key = serialization.load_pem_private_key(Path(name).read_bytes(), password=None)
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    print(name, raw.hex())
PY
```

在线环境里由密钥管理系统生成并只把私钥文件下发到控制台主机；手册中的路径都是示例，
不要把真实私钥值写进仓库、镜像、工单或聊天。

## 配置控制台

四个参数必须同时给出，私钥只从文件读 PEM，不接受环境变量：

```bash
adk-agent console --agents agents.py --ui vue \
  --role admin \
  --compose-key /etc/adk/compose.pem --compose-key-id compose-2026-11 \
  --compose-builder-key /etc/adk/compose-builder.pem --compose-builder-key-id builder-2026-11
```

- 只给一部分参数、或 key id 为空串：启动退出 2；私钥不可读或不是 Ed25519：退出 1。
- 四个都不给：`POST /api/compose` 返回 404 `compose_not_configured`，模板与预览仍可用。
- 密钥文件只允许控制台运行用户读取（0600 / 0400），不要给组或其他用户。
- 与审计签名密钥环（`ADK_AUDIT_KEYRING`）、凭据 KEK（`ADK_SECRET_KEKS`/Vault）完全分离，
  不要复用同一份私钥。

## 信任集

发布后的版本要能被读取端加载，需要把**发布公钥**加进读取端的信任集；
用 HTTP 注册表发布时，还要把**构建公钥**加进注册表的构建信任集：

| 位置 | 参数 | 环境变量 | 内容 |
|---|---|---|---|
| 控制台 / MCP / `serve*` 加载工件 | `--artifact-keys FILE` | `ADK_ARTIFACT_KEYS` | `{"compose-2026-11": "<32 字节 hex>"}` |
| 控制台 / MCP / `serve*` 载入 `in_process` 工件 | `--builder-keys FILE` | `ADK_BUILDER_KEYS` | `{"builder-2026-11": "<32 字节 hex>"}` |
| `serve-registry` 校验构建签名 | `--builder-keys FILE` | `ADK_BUILDER_KEYS` | 同上 |
| CLI `publish` 自查构建签名 | `--builder-keys FILE` | `ADK_BUILDER_KEYS` | 同上 |

密钥 id 要与 `--compose-key-id` / `--compose-builder-key-id` 完全一致。

载入侧同样强制（ADR-0044）：用 `--agent-ref` 载入 `in_process` 工件时，
`console`/`serve`/`serve-many`/`serve-a2a` 必须有构建信任集，缺失或验签失败退出 1；
文件注册表与 HTTP 注册表走同一段载入代码，没有「文件注册表不校验」的例外。
`sandboxed` 记录不要求构建签名。既有部署升级时把上面这行 `--builder-keys` 加到启动参数即可。
CLI `compose` 只负责签名，不校验构建签名；需要在发布前自查构建签名时用 `publish` 的
`--builder-keys`（或 `ADK_BUILDER_KEYS`）。

## 轮换

轮换是加法，任何一步都不需要重签历史工件：

1. 生成新的一对密钥，把新公钥按新 key id 加入读取端的 `--artifact-keys` 与注册表的
   `--builder-keys`，滚动所有读取端与注册表。
2. 确认读取端已认识新 key id 后，把控制台的四个 `--compose-*` 参数切到新文件与新 id，重启控制台。
3. 旧公钥继续留在信任集，直到所有用旧密钥签名的版本退役（`lifecycle set --status retired`）。
4. 全部旧版本退役后再删除旧公钥；删除后旧工件将无法通过验签与加载。

## 撤销与泄露处置

1. 先停用发布：去掉四个 `--compose-*` 参数并重启控制台，`POST /api/compose` 立即回到
   404 `compose_not_configured`；模板与预览不签名，可以保留。
2. 再从读取端与注册表的信任集里删除泄露 key id 对应的公钥。这一步会让该密钥签过、尚未退役的
   版本无法加载，是故意的 fail-closed。
3. 用审计排查：`agent.compose` 事件记录 `template_id`、租户/Agent/版本与工件 digest，
   不含指令原文。按 key id 与时间窗筛选发布记录，必要时把相关版本退役。
4. 审计签名密钥与凭据 KEK 若未共用，无需一起轮换；确认没有共用后分别评估。

## 最小权限

- 私钥只放在控制台主机，由专用系统用户持有；不要出现在进程参数快照之外的地方（参数只含路径）。
- 不要把私钥拷进容器镜像或 ConfigMap；Secret 挂载用只读卷并限制 RBAC。
- 备份策略里单独备份信任集（公钥）与私钥文件；恢复后先跑一次 `POST /api/compose/preview`
  确认模板与渲染可用，再用 `GET /api/registry` 确认注册表连通，最后做真实发布。
- 控制台本身就是签名路径：能触发 `POST /api/compose` 的主体等同发布权，按高价值目标加固
  （强认证、最小角色、审计告警）。
