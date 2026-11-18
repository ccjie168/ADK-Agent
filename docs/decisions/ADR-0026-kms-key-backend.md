# ADR-0026 密钥后端选型框架：端口已留，实现待选

状态: Accepted   日期: 2026-11-18   签字: Jie CAO（会话确认）

## 背景

ADR-0025 把租户凭据的密钥材料收进 `ADK_SECRET_KEKS`，并明确 KMS/Vault 走同一个 `KeyBackend`
端口。当前只有本地 KEK。这套平台的预期部署是企业内网，而内网里可用的密钥基础设施尚未确定：
可能已有 Vault，可能有硬件 HSM，也可能只能依赖 Kubernetes Secret 或文件挂载。

在这种情况下先写死一个云 KMS 实现是错的：它会引入一条内网不需要的出网依赖，还会把“密钥集中
管理”的收益绑在错误的假设上。这份 ADR 因此不选实现，只定义选型标准、共同契约，以及在没有外部
密钥服务期间先做什么。

**范围说明：** 这份 ADR 只谈“凭据密文的密钥放在哪”，不谈“谁可以调用”。内网身份认证已经由
OIDC 覆盖（ADR-0007）：AD、Entra ID 与 ADFS 都通过 OIDC 接入，角色与租户从 token 取。
LDAP、Kerberos/SPNEGO 或 Windows 集成认证如果确实需要，属于 identity 适配器，另立 ADR，
不与密钥后端混在一起。

## 决定

1. **保持一个端口。** `KeyBackend` 继续只有 `wrap`、`unwrap`、`rewrap`、`current_key_id`。
   任何后端都实现这四个方法，调用方不按后端分支。选型不改变 ADR-0025 的对外语义：
   存储只存密文、运行时 fail-closed、轮换不把凭据明文带进内存。

2. **暂不锁定后端。** 候选与适用条件：

   | 后端 | 适用前提 | 主要代价 |
   | --- | --- | --- |
   | Vault Transit | 内网已有高可用 Vault | 可选依赖 `hvac`；Vault 本身要运维 |
   | PKCS#11 / KMIP HSM | 已有硬件 HSM 或 KMIP 网关 | 厂商客户端库；集成与测试成本最高 |
   | 加固的本地 KEK | 没有外部密钥服务 | 密钥在进程内存；多副本各持一份 |
   | 云 KMS（AWS/GCP/Azure） | 内网经专线或私有端点访问云 | 出网依赖；IAM 与端点配置 |

   选型由部署方按上表判断，本 ADR 不预设顺序。

3. **过渡期做本地 KEK 加固，不新增依赖。**
   - keyring 除 `ADK_SECRET_KEKS` 外支持 `ADK_SECRET_KEKS_FILE`，从只读文件读取；两者同时设置
     时启动退出 1。
   - POSIX 上要求 keyring 文件不可被组或其他用户读取（mode 0600/0400），否则启动退出 1；
     Windows 跳过该检查并在文档里说明。
   - 安装手册与运维手册写明：文件由 Secret 卷或 systemd credentials 注入，不写入镜像、
     不写入 `.env`、不进日志。
   - `credentials rewrap` 仍是轮换入口；删除旧 key 前的要求按发布说明。

4. **选型后新增后端时，格式与配置规则固定：**
   - 密文 payload 升到 `v: 2`，带 `backend` 字段；`v: 1` 按本地 KEK 兼容读取，新写入一律 `v: 2`。
   - `ADK_SECRET_BACKEND=local|<backend>` 显式选择，缺省 `local`；对应后端的凭据缺失或与
     本地 keyring 同时配置时启动退出 1。
   - 新后端依赖作为可选 extra（例如 `kms-vault`），默认不装；没装而选了该后端时启动失败并给出提示。
   - AAD 仍是 `adk-credential:<tenant>:<credential_id>`；云端加密上下文从记录推导，不从请求体取。

5. **失败语义对所有后端一致。** 后端不可达、权限不足、密钥禁用或解密失败都按“凭据不可用”处理：
   `TenantSecretProvider` 抛 `SecretNotFound`，工具网关与远程 agent 回 `secret_unavailable`，
   控制面与 CLI 回 503/退出 1。**没有本地回退**；DEK 不在进程内缓存。

6. **审计补齐。** 实现 ADR-0025 第 8 条遗留的 `credential.decrypt_failed`：解密或后端调用失败时
   写一条审计，带 `key_id` 与 `error_code`，不带明文、密文或请求体。

## 备选与否决

- **先做 AWS KMS**：内网部署多一条出网依赖，收益依赖“已经在 AWS 上”的假设；否决为先做。
- **KMS 失败回退本地 KEK**：会让已撤销的本地密钥重新生效，违背 fail-closed；否决。
- **进程内缓存 DEK**：降低延迟但扩大密钥驻留面；暂不做，需要时单独 ADR。
- **继续只靠环境变量**：多副本泄露面大、轮换难；作为过渡可接受，但必须按第 3 条加固。

## 后果

- 选型前不引入云依赖；本地 KEK 的加固先落地，内网部署的密钥面收窄到只读文件。
- 选型后按第 4 条接入，不需要改运行时、写入路径或存储字段。
- 过渡期残余风险：密钥仍在进程内存中，多副本各持一份；文档如实记录。

## 切片（待确认后分配）

1. 本地 KEK 加固：`ADK_SECRET_KEKS_FILE`、文件权限检查、启动互斥、文档。
2. `credential.decrypt_failed` 审计（与后端无关，可先做）。
3. 选型确定后：`v: 2` 格式与分派、所选后端的实现与可选 extra、配置接线。

## 确认记录

2026-11-18 会话确认：采纳本框架，不预设密钥后端；过渡期先做本地 KEK 加固（`ADK_SECRET_KEKS_FILE`、POSIX 权限检查、与 `ADK_SECRET_KEKS` 互斥）与 `credential.decrypt_failed` 审计，具体后端待内网基础设施确定后再选。
