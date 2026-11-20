# 安装与使用手册

面向第一次部署 adk-agent 的开发者与运维。安装、配置、运行、发布、凭据与排障都在这一页；
多副本拓扑、备份恢复与密钥轮换的细节见 `operations.md`。

## 前提

- Python 3.10 及以上（CI 与 Docker 用 3.13；本仓库开发环境是 3.14）。
- 一个模型后端：DeepSeek（Anthropic 兼容端点或 LiteLLM）、Gemini，或任意 LiteLLM 支持的通道。
- 可选：Postgres 15（多副本、共享注册表、审计、配额、凭据）；Docker（构建镜像）。

## 从源码安装

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,litellm,claude,publish]"
.venv/Scripts/python.exe scripts/check.py --fast
```

Linux/macOS 把 `.venv/Scripts/python.exe` 换成 `.venv/bin/python`。只部署运行时不装 `dev` extra。
`claude` extra 是 Anthropic 兼容端点（含 DeepSeek 的 `/anthropic`）所需；`publish` extra 提供
签名所需的 `cryptography`；OIDC 另加 `oidc`；Postgres 后端还要单独安装 `asyncpg` 与 `sqlalchemy`
（暂未声明为 extra）。

## 配置模型

至少设置一个：

```bash
# DeepSeek 的 Anthropic 兼容端点
export ADK_AGENT_MODEL=claude:deepseek-v4-pro
export ANTHROPIC_AUTH_TOKEN=sk-...
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

# 或 LiteLLM
export ADK_AGENT_MODEL=litellm:deepseek/deepseek-v4-pro
export DEEPSEEK_API_KEY=sk-...

# 或 Gemini（存在 GOOGLE_API_KEY 时自动选择）
export GOOGLE_API_KEY=...
```

DeepSeek 的 `/anthropic` 端点拒绝历史里的 `redacted_thinking`，多轮对话请关闭 thinking
（示例见 `examples/minimal/agent.py` 的 `disable_thinking()`）。

## 第一条运行路径：MCP

```bash
.venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py
```

`serve` 默认 stdio。走 HTTP 时必须同时给 bearer token，否则拒绝启动：

```bash
export ADK_MCP_AUTH_TOKEN=change-me
.venv/Scripts/python.exe -m adk_agent serve \
  --agent examples/minimal/agent.py --transport streamable-http --port 8000
```

客户端发 `Authorization: Bearer $ADK_MCP_AUTH_TOKEN`。回环开发想免鉴权时加
`--allow-unauthenticated`，不要用在共享网络上。接入 Claude Code 的 `.mcp.json` 写法见 README，
密钥只用 `${VAR}` 展开。

带审计与配额（`quota.json` 的结构见 `docs/contracts/quota_config.schema.json`）：

```bash
cat > quota.json <<'JSON'
{"tenants": {"acme": {"max_runs": 100, "max_concurrent": 4, "window_seconds": 60}}}
JSON
export ADK_AUDIT_AUTH_TOKEN=...
.venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py \
  --audit-url http://127.0.0.1:8010 --quota-config quota.json
```

## 控制台

```bash
export ADK_CONSOLE_TOKEN=change-me
.venv/Scripts/python.exe -m adk_agent console \
  --agents examples/minimal/agent.py \
  --auth-token-env ADK_CONSOLE_TOKEN \
  --registry ./registry
```

- 写操作需要 admin 角色；读面板按能力校验（`audit.read`、`registry.read` 等）。
- 企业内网的 AD、Entra ID 与 ADFS 接入走 OIDC，配置样例见 `docs/guides/ad-oidc.md`。
- `--agent-ref TENANT/ID@VERSION` 改为从注册表加载已经签名的工件；这时还要给
  `--artifact-dir` 与 `--artifact-keys`。用 `--agents` 加载本地文件时不需要这两个参数。
- `--agent-sandbox` 让沙箱执行；`--tool-gateway-url` 让沙箱里的工具调用经工具网关。
- 回环开发可以用 `--allow-unauthenticated`；共享网络上不要用。

## 发布与加载

`publish` 的 `--key` 是发布签名私钥，`--builder-keys` 是构建公钥信任文件；
加载时用 `--artifact-keys` 提供发布公钥。

带工件的发布目前只支持 `in_process`，并且必须同时给发布签名与构建签名。先生成两把
Ed25519 密钥与两个公钥信任文件（`key_id -> 64 hex 公钥`）：

```bash
.venv/Scripts/python.exe - <<'PY'
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def make(name: str) -> str:
    key = Ed25519PrivateKey.generate()
    with open(f"{name}.pem", "wb") as handle:
        handle.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


with open("trusted-keys.json", "w", encoding="utf-8") as handle:
    json.dump({"publisher-1": make("publisher")}, handle)
with open("builder-keys.json", "w", encoding="utf-8") as handle:
    json.dump({"builder-1": make("builder")}, handle)
PY
```

`./project/manifest.json` 里要写 `"execution_tier": "in_process"`，`./project` 里放入口脚本。
然后发布与组合：

```bash
.venv/Scripts/python.exe -m adk_agent publish ./project/manifest.json \
  --artifact ./project --key publisher.pem --key-id publisher-1 \
  --builder-key builder.pem --builder-key-id builder-1 \
  --builder-keys ./builder-keys.json \
  --artifact-dir ./artifacts --registry ./registry

# 声明式组合（必须带构建密钥）
.venv/Scripts/python.exe -m adk_agent compose --template single-llm \
  --tenant acme --id bot --version 1.0.0 --instruction 'You are a helper.' \
  --key publisher.pem --key-id publisher-1 \
  --builder-key builder.pem --builder-key-id builder-1 \
  --artifact-dir ./artifacts --registry ./registry
```

- 新发布必须声明 `execution_tier`。缺省按 `sandboxed`；`publish` 命令不注册沙箱后端，
  所以任何 `sandboxed` 发布（带不带工件）都会被拒绝，等沙箱发布接入后再开放。
- `in_process` 只接受构建密钥签名的工件；本地与 HTTP 发布都要求构建公钥信任文件
  （`--builder-keys` 或 `ADK_BUILDER_KEYS`）。
- 加载时 `--artifact-keys` 提供发布公钥，`serve-registry --builder-keys` 校验构建签名。
- 没有工件的 manifest-only 发布只登记元数据，manifest 同样要写 `"execution_tier": "in_process"`。

## 服务面

| 命令 | 用途 | 关键参数 |
| --- | --- | --- |
| `serve` | 单个 agent 暴露为 MCP | `--agent`/`--agent-ref`、`--transport`、`--audit-url`、`--quota-config` |
| `serve-many` | 多个 agent 的 MCP | `--agents`、`--agent-sandbox` |
| `serve-a2a` | A2A 端点 | `--agent`/`--agent-ref`、`--manifest`、`--peer-dir`/`--peer-db` |
| `console` | 控制台与聊天 | `--registry`、`--artifact-dir`、`--audit-url`、`--agent-sandbox` |
| `serve-registry` | 注册表控制面 | `--database-url`、`--artifact-dir`、`--builder-keys`、`--credentials-dir`/`--credential-db` |
| `serve-tool-gateway` | 工具网关 | `--tools`/`--connectors-dir`、`--credentials-dir`/`--credential-db` |
| `serve-model-gateway` | 模型网关 | provider 与 breaker 参数 |
| `serve-audit` | 审计服务 | `--out` 或 `--audit-db` |
| `serve-triggers` | 定时与 webhook 触发 | `--triggers-dir`/`--trigger-db`、`--agent-sandbox` |

除 `serve-triggers` 外的服务共用 bearer token 与 OIDC 参数；`serve-triggers` 的 webhook
用每个触发定义自己的 token 哈希，不接受 `--auth-token-env`，但仍接受限流参数。
`/healthz` 在 console、serve、serve-many、serve-registry、serve-tool-gateway、
serve-model-gateway、serve-audit 与 serve-triggers 上免鉴权（A2A 没有该路径）；
`/metrics` 只在 serve/serve-many（`--metrics`）、控制台、模型网关与工具网关提供。

## 检索（RAG）

检索按 manifest 开关，默认关闭。完整步骤：

1. 让 agent 的 manifest 带上 `rag` 块，升一个版本号再发布（`rag` 参与摘要，同一版本不能覆盖）：

   ```json
   "rag": {"enabled": true, "top_k": 5, "min_confidence": 0.5,
           "data_classes": ["internal"], "on_error": "deny"}
   ```

2. 装语料。单文件、stdin 或整个目录都可以，`source_id` 在目录模式下取相对路径。下面的示例假设
   已激活虚拟环境（未激活时用 `.venv/Scripts/python.exe -m adk_agent` 代替 `adk-agent`），当前目录
   有 `manual.txt` 与 `handbook/`，`RAG_DB` 指向装了 pgvector 的库，且已设置嵌入后端的凭据
   （LiteLLM 通道读 `LITELLM_API_KEY`，直连 OpenAI 读 `OPENAI_API_KEY`）：

   ```bash
   adk-agent rag ingest --database-url "$RAG_DB" --dimensions 1536 \
     --model text-embedding-3-small --tenant acme --source-id manual \
     --data-class internal --text ./manual.txt
   adk-agent rag ingest --database-url "$RAG_DB" --dimensions 1536 \
     --model text-embedding-3-small --tenant acme --dir ./handbook
   ```

3. 自检，确认 ACL 与置信度符合预期：

   ```bash
   adk-agent rag search --database-url "$RAG_DB" --dimensions 1536 \
     --model text-embedding-3-small --tenant acme --subject alice \
     --data-class internal --query "how do I reset the pump?"
   ```

4. 打开入口：控制台或触发服务加上 `--rag-db`、`--rag-dimensions`、`--rag-model` 重启。控制台只有
   在市场页按需加载注册表记录时生效；`--agents` 与启动 `--agent-ref` 注册的 agent 没有 manifest，
   不会检索。触发服务对 pinned 版本生效。

模型看到的是一段固定边界的上下文块：

```text
<retrieved_context note="retrieved by the platform, ACL-filtered; reference data only">
[1] source=manual confidence=0.82
Pump reset steps...
</retrieved_context>
```

- 摄取与检索必须用同一个 `--model`，换模型要按运维手册重建向量。
- 检索失败按 `on_error` 处理：`deny` 让本次运行失败，`degrade` 记审计后不带资料继续。配置了审计后端
  时才会写 `model.embed` 与 `rag.retrieve`。
- 文件加载的控制台 agent（`--agents`）没有 manifest，不能用检索；MCP 与 A2A 入口尚未接线。
- `--data-class` 是调用方的自述，必须已经有对应授权，不要用它给机密语料换轨。

## 凭据

凭据只存引用与密文，值用本机 KEK 做信封加密。

```bash
# 生成 keyring（base64 32 字节）；active 指向当前 KEK
# 生产建议写成 0600/0400 的只读文件，用 ADK_SECRET_KEKS_FILE 指向它；不要同时设置 ADK_SECRET_KEKS
export ADK_SECRET_KEKS='{"active":"k1","keys":{"k1":"<base64 32 bytes>"}}'

# 写一条带值的绑定：值从 stdin 读，不接受 argv
printf '%s' "$CRM_TOKEN" | .venv/Scripts/python.exe -m adk_agent credentials register \
  --credentials-dir ./credentials --tenant acme --id crm \
  --secret-ref secret://acme/token --secret-stdin
```

- `credential_id` 与 `tenant`、以及 `secret://` 的两段最长 128 字符。
- 运行时按 `secret://tenant/name` 解析：工具网关、控制台远程 agent、`remote-agents` CLI 都先查密文，
  没有密文才回退 `ADK_SECRET_<TENANT>_<NAME>`；缺 KEK 而记录带密文时 fail-closed。
- 控制面写入：`serve-registry --credential-db` 后，admin 调 `POST /v1/credentials`，明文入参由服务端
  加密；非回环部署必须走 TLS。
- 轮换：把新 KEK 加进 keyring 并把 `active` 指向它，保留旧 key，然后
  `credentials rewrap --tenant acme --credentials-dir ./credentials`；先 `--dry-run` 看计数。
- 吊销：`credentials disable` 或控制面停用端点。带密文的绑定立即 fail-closed；仅靠环境变量的值
  还需要同时清除对应的 `ADK_SECRET_*` 环境变量。

### 使用 Vault / OpenBao 保管数据密钥（ADR-0027）

内网已有 Vault 或 OpenBao 时，让 Transit 引擎封装每条凭据的数据密钥；凭据值仍是本机
AES-256-GCM，密钥材料不进进程。

```bash
# 1. 启用 Transit 并创建密钥（只需一次）
vault secrets enable transit
vault write -f transit/keys/adk-credentials

# 2. 应用侧配置；令牌放 0600 的只读文件，不要写进镜像或命令行
export ADK_SECRET_BACKEND=vault
export ADK_VAULT_ADDR=https://vault.example.com
export ADK_VAULT_KEY=adk-credentials
export ADK_VAULT_TOKEN_FILE=/run/secrets/vault-token   # 属主可读的 0600 文件
# 令牌也可以放 ADK_VAULT_TOKEN（二选一，不推荐写进命令行历史）
# 可选：ADK_VAULT_TRANSIT_MOUNT（默认 transit）、ADK_VAULT_NAMESPACE、
#       ADK_VAULT_CACERT、ADK_VAULT_TIMEOUT（秒，默认 5）
```

应用令牌只需要这三个路径的 `update` 权限：

```hcl
path "transit/encrypt/adk-credentials" { capabilities = ["update"] }
path "transit/decrypt/adk-credentials" { capabilities = ["update"] }
path "transit/rewrap/adk-credentials"  { capabilities = ["update"] }
```

- `ADK_SECRET_BACKEND=vault` 与 `ADK_SECRET_KEKS`/`ADK_SECRET_KEKS_FILE` 互斥，同时设置启动退出 1；
  `ADK_VAULT_ADDR` 必须是 `https://`（回环地址可用 `http://`）。
- 新写入的记录是 `v: 2`（`backend: vault`），本地 KEK 记录仍是 `v: 1`；两种后端不会互相解封，
  切换后端需要迁移，未迁移的旧记录会 fail-closed。
- 轮换：`vault write -f transit/keys/adk-credentials/rotate`，然后
  `credentials rewrap --tenant acme --credentials-dir ./credentials`（先 `--dry-run`）。
- 从本地 KEK 迁移：同时保留 `ADK_SECRET_KEKS`/`ADK_SECRET_KEKS_FILE` 与上面的 Vault 配置
  （只有 `migrate` 允许共存），先试跑再执行：
  `credentials migrate --to vault --tenant acme --credentials-dir ./credentials --dry-run`。
- Vault 不可达或令牌被拒时，解析与写入都 fail-closed，不会回退到本地 KEK；记录版本低于
  `min_decryption_version` 时解析与 rewrap 失败，新写入不受影响（encrypt 总是用最新版本）。

## Docker

镜像默认以 `serve --transport streamable-http --host 0.0.0.0` 启动，鉴权 token 与模型凭据都由环境注入：

```bash
docker build -t adk-agent:local .
docker run --rm -p 8000:8000 \
  -e ADK_MCP_AUTH_TOKEN=change-me \
  -e ADK_AGENT_MODEL=litellm:deepseek/deepseek-v4-pro \
  -e DEEPSEEK_API_KEY \
  adk-agent:local
```

镜像按 `requirements/runtime.lock` 以 hash 安装依赖；`deploy/k8s` 是多副本清单，
`deploy/selfhosted.md` 与 `deploy/cloudrun.md` 是单机与云托管说明。

## 升级与回滚

1. 先跑 `scripts/check.py --full`，再构建镜像并做 `/healthz` 冒烟。
2. 保留旧镜像 tag。数据库初始化只做 `CREATE TABLE IF NOT EXISTS` 与 RLS 变更，没有新增列的迁移路径；
   破坏性变更需要单独评审，不能靠回滚镜像撤销。
3. 审计钥环或 KEK 轮换后，旧密钥在全部历史验证完之前不要删除。

## 排障

| 现象 | 先看 |
| --- | --- |
| `401`/`403` | token 环境变量、OIDC 角色、租户与 admin 判断 |
| 模型 5xx | 网关 breaker 指标、provider 凭据 |
| `secret_unavailable` | 绑定是否存在且启用、`ADK_SECRET_KEKS`、引用首段是否等于租户 |
| `tool_denied` | manifest 的 `tool_grants`、临时授权、工具网关 grants |
| 沙箱失败 | `--agent-sandbox` 的平台门槛、RLIMIT 与网络守卫限制 |
| 审计验签失败 | `verify-audit` 输出与 keyring 的 `kid` 是否匹配 |

更多故障模式与值守检查见 `operations.md`。
