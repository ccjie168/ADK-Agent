# SLICE-203 审计链校验的运维说明

状态: gated
依据: ADR-0037（Accepted 2026-11-21）切片 3。

## 意图

1. 运维手册的「值守检查」写清 `verify-audit` 校验的是**存储内容**，升级新增审计字段不会断链；
   历史记录（包括 SLICE-188 之前的）按原样通过。
2. 说明断链报告的含义：序号、租户，以及「升级后突然全部通过」不是规则放松。
3. 指向 `docs/contracts/audit_chain.md` 的哈希口径。

## 契约（先改）

- 无契约变更；`docs/contracts/audit_chain.md` 已在 SLICE-201 定义口径。

## 完成判据

- [x] 值守检查写明校验口径与历史记录可验 -> `test_operations_guide_explains_audit_chain_hashing`
- [x] 手册指向 `docs/contracts/audit_chain.md` -> `test_operations_guide_links_audit_chain_contract`
- [x] 全量门禁通过

## 反例

- [x] 基线手册没有「存储内容」与 ADR-0037 的说法
- [x] 手册若写「升级会断链」与 ADR 相反，用例应失败

## 5 问威胁建模

1. **数据**：运维对审计链校验的理解与处置流程。
2. **调用方**：值守与发布人员。
3. **信任边界**：文档 → 运维判断。
4. **恶意输入最坏结果**：把断链误判为正常升级现象而忽略真实篡改。缓解：写明断链只可能来自内容
   变化（存储被改），并给出定位方式。
5. **失败是否泄露信息**：无代码变更。

## 范围外

- `verify-audit` 命令输出格式变更（当前输出已够用）。
- 历史不一致记录迁移（已否决）。

## 证据

- `docs/evidence/SLICE-203-audit-chain-docs.txt`
