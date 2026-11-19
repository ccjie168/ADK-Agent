# SLICE-161 Vault 密钥后端的安装与运维文档

状态: gated
依据: ADR-0027 切片 3：契约之外还要让安装手册与运维手册覆盖 Vault 配置、策略、轮换与失败模式。

## 意图

1. `docs/guides/install-and-use.md` 的凭据段新增 Vault/OpenBao 小节：启用 Transit、创建密钥、
   环境变量、最小权限策略（`encrypt`/`decrypt`/`rewrap` 的 `update`）、与本地 keyring 互斥、
   `v: 2`/`v: 1` 兼容与 fail-closed、轮换命令。
2. `docs/guides/operations.md` 的密钥轮换补 Vault 条目：轮换顺序、`min_decryption_version`
   风险、Vault 不可达时的表现；环境变量段落与故障模式表补对应行。
3. `tests/test_vault_guide.py` 校验：源码里的每个 `ADK_VAULT_*` 变量都出现在安装手册；
   Transit 路径与 rotate 命令存在；运维手册覆盖轮换、失败模式与关键变量。

## 契约（先改）

- 不需改对外接口；`docs/contracts/credentials.md` 与 `cli.md` 已在 SLICE-160 更新。

## 完成判据

- [x] 安装手册覆盖全部 `ADK_VAULT_*` 变量与 `ADK_SECRET_BACKEND=vault` -> `test_install_guide_names_every_vault_variable`
- [x] Transit 初始化、策略路径与 rotate 命令在安装手册 -> `test_install_guide_has_the_transit_setup_and_policy`
- [x] 运维手册覆盖轮换、故障与关键变量 -> `test_operations_guide_covers_rotation_and_failure`
- [x] 既有安装手册用例保持通过 -> `test_install_guide.py`
- [x] 全量门禁通过

## 反例

- [x] 基线文档没有 Vault 小节，三个用例在基线上失败（变量与命令缺失）

## 5 问威胁建模

1. **数据**：Vault 令牌、Transit 密钥名、凭据密文。
2. **调用方**：部署与运维该服务的工程师。
3. **信任边界**：文档示例到真实部署。
4. **恶意输入最坏结果**：示例把令牌写进命令行或镜像（缓解：只演示 0600 文件）；
   策略给过宽权限（缓解：只列三个路径的 update）；轮换删旧版本导致 fail-closed（缓解：写明顺序）。
5. **失败是否泄露信息**：文档不含真实令牌或地址。

## 范围外

- `credentials migrate --to vault` 命令与其文档（ADR-0027 切片 4，需单独评审）。
- live Vault 验证与 TLS 配置排查。

## 证据

- `docs/evidence/SLICE-161-vault-docs.txt`
