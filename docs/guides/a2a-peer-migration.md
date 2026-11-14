# A2A 从共享 token 迁移到 peer 模式

面向已经用 `serve-a2a --auth-token-env` 上线、准备切到 ADR-0014 peer 模式的运维。两种模式互斥，同一进程只能选一种。

## 前置条件

- 被暴露的 agent 有已发布 manifest，且 `exposure` 为 `a2a`。
- 每个调用方有稳定身份：内部 OIDC 的 subject，或可以单独分发并轮换的 token。
- A2A 的审计与平台其他服务汇到同一处（`--audit-url` 或共享 `--audit-file`），否则 peer 身份切换后报表会对不上。

## 步骤

1. **清点调用方。** 列出当前持共享 token 的系统，给每个分配 `peer_id` 与租户。一个调用方对多个 agent 时仍只注册一个 peer。
2. **注册 peer。** 文件存储用 `--peer-dir`，共享部署用 `--peer-db`。

   ```bash
   adk-agent peers register --peer-dir /srv/adk/peers \
     --id crm-bot --tenant acme --subject sub-crm-bot --kind service
   ```

3. **准备身份。** OIDC 模式配置内部 issuer，并让 peer 的 `subject` 与 token 的 `sub` 一致；token 模式生成每个 peer 的凭据并把哈希写进文件。

   ```bash
   python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" '<token>'
   ```

   ```json
   {"crm-bot": "<64 hex sha256>"}
   ```

   文件里不放明文 token。轮换时替换哈希并重启服务。

4. **写授权。** 没有记录即拒绝。

   ```bash
   adk-agent peers grant --peer-dir /srv/adk/peers \
     --id crm-bot --agent bot --actions read,invoke
   ```

5. **切换启动参数。** 去掉 `--auth-token-env`，加 peer 参数，重启。

   ```bash
   adk-agent serve-a2a --agent agent.py \
     --manifest manifest.json \
     --peer-dir /srv/adk/peers \
     --peer-token-file /srv/adk/peer-tokens.json \
     --port 8800
   ```

   同一命令里再出现 `--auth-token-env` 或 `--allow-unauthenticated` 会直接退出 2。

6. **验证。**

   | 请求 | 期望 |
   | --- | --- |
   | 旧共享 token 访问 card | 401 |
   | 新 peer token，只有 `read`，访问 card | 200 |
   | 新 peer token，只有 `read`，`message/send` | 403，JSON-RPC `-32001` |
   | 新 peer token，只有 `invoke`，访问 card | 404 |
   | 新 peer token，`invoke`，`message/send` | 进入 agent |
   | 停用后的 peer | 403 |

   同时确认审计里 `agent.run` 的 `tenant` 与 `principal.subject` 已经是 peer，而不再是 `local` 与 `a2a_user`。

## 回滚

换回 `--auth-token-env` 与共享 token，重启即可。peer 记录与授权留在存储里不影响 legacy 模式。

同一时间只能有一个模式生效。需要灰度时另起一个端口跑 legacy 实例，由网关或 DNS 分流，不要在同一进程里混用。

## 排障

- **401**：没有 bearer、token 哈希不在文件、或 OIDC token 无效。
- **403**：peer 被停用、租户不符、或没有对应动作的授权。
- **404**：`read` 授权缺失时 card 被隐藏；先确认 peer 是否有 `read`。
- **启动失败**：检查 manifest 的 `exposure` 是否为 `a2a`，以及 `--peer-dir`/`--peer-db` 是否只给了一个。

## 迁移后要改的地方

- 按 `local/a2a_user` 写的审计报表与告警要改成按 peer 租户与 peer id 过滤。
- 共享 token 从密钥系统里吊销，避免旧凭据继续留在调用方。
- 调用方拉取 agent card 的客户端可能缓存了旧 card；切模式后 card 内容不变，但鉴权头要换。
