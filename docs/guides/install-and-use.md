# 安装与使用手册

面向第一次部署 adk-agent 的开发者与运维。安装、配置、运行、发布、凭据与排障都在这一页；
多副本拓扑、备份恢复与密钥轮换的细节见 `operations.md`。

## 前提

- Python 3.13 或 3.14（本仓库的开发环境是 3.14）。
- 一个模型后端：DeepSeek（Anthropic 兼容端点或 LiteLLM）、Gemini，或任意 LiteLLM 支持的通道。
- 可选：Postgres 15（多副本、共享注册表、审计、配额、凭据）；Docker（构建镜像）。

## 从源码安装

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev,litellm]"
.venv/Scripts/python.exe scripts/check.py --fast
```

Linux/macOS 把 `.venv/Scripts/python.exe` 换成 `.venv/bin/python`。只部署运行时不装 `dev` extra。

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

`serve` 默认 stdio；加 `--transport streamable-http --port 8000` 走 HTTP。接入 Claude Code 的
`.mcp.json` 写法见 README，密钥只用 `${VAR}` 展开。

带审计与配额：

```bash
export ADK_AUDIT_AUTH_TOKEN=...
.venv/Scripts/python.exe -m adk_agent serve --agent examples/minimal/agent.py \
  --audit-url http://127.0.0.1:8010 --quota-config quota.json
```

## 控制台

```bash
.venv/Scripts/python.exe -m adk_agent console \
  --agents examples/minimal/agent.py \
  --auth-token-env ADK_CONSOLE_TOKEN \
  --registry ./registry \
  --artifact-dir ./artifacts \
  --artifact-keys ./trusted-keys.json
```

- 写操作需要 admin 角色；读面板按能力校验（`audit.read`、`registry.read` 等）。
- `--agent-ref TENANT/ID@VERSION` 改为从注册表加载已经签名的工件。
- `--agent-sandbox` 让沙箱执行；`--tool-gateway-url` 让沙箱里的工具调用经工具网关。

## 发布与加载

```bash
# 打包并签名工件
.venv/Scripts/python.exe -m adk_agent publish ./project/manifest.json \
  --artifact ./project --key publisher.pem --key-id publisher-1 \
  --builder-key builder.pem --builder-key-id builder-1 \
  --artifact-dir ./artifacts --registry ./registry

# 声明式组合（必须带构建密钥）
.venv/Scripts/python.exe -m adk_agent compose --template single-llm \
  --param name=bot --param tenant=acme --param instruction='...' \
  --key publisher.pem --key-id publisher-1 \
  --builder-key builder.pem --builder-key-id builder-1 \
  --artifact-dir ./artifacts --registry ./registry
```

新发布必须声明 `execution_tier`；缺省按 `sandboxed`。`in_process` 只接受构建密钥签名的工件。
加载时 `--artifact-keys` 提供可信公钥，`serve-registry --builder-keys` 校验构建签名。

## 服务面

| 命令 | 用途 | 关键参数 |
| --- | --- | --- |
| `serve` | 单个 agent 暴露为 MCP | `--agent`/`--agent-ref`、`--transport`、`--audit-url`、`--quota-config` |
| `serve-many` | 多个 agent 的 MCP | `--agents`、`--agent-sandbox` |
| `serve-a2a` | A2A 端点 | `--agent`/`--agent-ref`、`--manifest`、`--peer-dir`/`--peer-db` |
| `console` | 控制台与聊天 | `--registry`、`--artifact-*`、`--audit-*`、`--agent-sandbox` |
| `serve-registry` | 注册表控制面 | `--database-url`、`--artifact-*`、`--builder-keys`、`--credentials-*` |
| `serve-tool-gateway` | 工具网关 | `--tools`/`--connectors-dir`、`--credentials-*` |
| `serve-model-gateway` | 模型网关 | provider 与 breaker 参数 |
| `serve-audit` | 审计服务 | `--out` 或 `--audit-db` |
| `serve-triggers` | 定时与 webhook 触发 | `--triggers-dir`/`--trigger-db`、`--agent-sandbox` |

全部服务的鉴权、限流与 OIDC 参数一致；`/healthz` 免鉴权，`/metrics` 需要 token。

## 凭据

凭据只存引用与密文，值用本机 KEK 做信封加密。

```bash
# 生成 keyring（base64 32 字节）；active 指向当前 KEK
export ADK_SECRET_KEKS='{"active":"k1","keys":{"k1":"<base64 32 bytes>"}}'

# 写一条带值的绑定：值从 stdin 读，不接受 argv
printf '%s' "$CRM_TOKEN" | .venv/Scripts/python.exe -m adk_agent credentials register \
  --credentials-dir ./credentials --tenant acme --id crm \
  --secret-ref secret://acme/token --secret-stdin
```

- 运行时按 `secret://tenant/name` 解析：工具网关、控制台远程 agent、`remote-agents` CLI 都先查密文，
  没有密文才回退 `ADK_SECRET_<TENANT>_<NAME>`；缺 KEK 而记录带密文时 fail-closed。
- 控制面写入：`serve-registry --credential-db` 后，admin 调 `POST /v1/credentials`，明文入参由服务端
  加密；非回环部署必须走 TLS。
- 轮换：把新 KEK 加进 keyring 并把 `active` 指向它，保留旧 key，然后
  `credentials rewrap --tenant acme --credentials-dir ./credentials`；先 `--dry-run` 看计数。
- 吊销：`credentials disable` 或控制面停用端点；吊销立即生效，已经解析过的明文不缓存。

## Docker

```bash
docker build -t adk-agent:local .
docker run --rm -p 8000:8000 \
  -e ADK_AGENT_MODEL=litellm:deepseek/deepseek-v4-pro \
  -e DEEPSEEK_API_KEY \
  adk-agent:local
```

镜像按 `requirements/runtime.lock` 以 hash 安装依赖；`deploy/k8s` 是多副本清单，
`deploy/selfhosted.md` 与 `deploy/cloudrun.md` 是单机与云托管说明。

## 升级与回滚

1. 先跑 `scripts/check.py --full`，再构建镜像并做 `/healthz` 冒烟。
2. 保留旧镜像 tag；数据库迁移是向前兼容的建表与加列，回滚镜像即可。
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
