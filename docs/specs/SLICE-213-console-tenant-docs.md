# SLICE-213 无 OIDC 控制台的租户说明

状态: gated
依据: PROGRESS 已知缺口第 10 条第 4 项（无 OIDC 的控制台主体租户固定为 `local`，正式部署需 OIDC claim）。

## 意图

1. 运维与使用手册写明：没有 `--oidc-config` 时，控制台主体的租户固定为 `local`、用户为
   `console_user`，角色来自 `--role`；此时 RAG、审计与配额都只覆盖 `local`。
2. 同一段写明正式部署用 OIDC，租户取自 token 的 `tenant` claim（`tenant_claim` 可改名），
   缺少该 claim 的 token 被拒绝。
3. 不改代码：行为已经如此，缺的是可见的说明与锁定用例。

## 契约（先改）

- 本切片只改手册；没有对外接口变化，`docs/contracts/` 不动。

## 完成判据

- [x] 两份手册都写明 `local`、`console_user` 与 `tenant_claim` -> `test_guides_state_the_token_only_tenant`
- [x] 使用手册把 OIDC 标为正式部署路径 -> `test_install_guide_marks_oidc_as_the_production_path`
- [x] 全量门禁通过

## 反例

- 基线 `a41c9b8`：两份手册都没有这些句子，三个用例 `AssertionError` / `ValueError` 失败。

## 5 问威胁建模

1. **数据**：控制台主体的租户归属，进而决定 RAG、审计与配额的范围。
2. **调用方**：部署控制台的运维与安全评审。
3. **信任边界**：鉴权方式 → 租户范围。
4. **恶意输入最坏结果**：运维以为共享 token 的控制台能看到别的租户或已启用检索，实际全部落在
   `local`；或反过来以为正式部署不需要 OIDC。缓解：把两条路径写在同一段，并说明 OIDC 缺 claim 即拒绝。
5. **失败是否泄露信息**：只在文档里描述语义，不含真实租户名或 IdP 地址。

## 范围外

- 让无 OIDC 的控制台选择租户（会绕过鉴权，另行评审）。
- `serve-triggers` 的租户语义（触发主体来自 `trigger:<id>`，本次不写）。

## 证据

- `docs/evidence/SLICE-213-console-tenant-docs.txt`
