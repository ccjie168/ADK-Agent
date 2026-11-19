# SLICE-181 OBO 后置说明文档

状态: gated
依据: ADR-0031（Accepted 2026-11-19）决定 3 / slice 4：OBO / 委托身份后置 P2，引入前需新 ADR。
本切片只补说明文档。

## 意图

1. `docs/guides/obo-deferral.md` 说明 OBO 后置的现状、原因、引入条件与新 ADR 门槛。

## 契约（先改）

- 无对外接口变更（纯文档）。

## 完成判据

- [ ] 文档存在 -> `test_obo_doc_exists`
- [ ] 文档声明后置与 P2 -> `test_obo_doc_states_deferral`
- [ ] 文档要求新 ADR -> `test_obo_doc_requires_new_adr`
- [ ] 文档列明引入条件 -> `test_obo_doc_names_reentry_conditions`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `docs/guides/obo-deferral.md`

## 5 问威胁建模

1. **数据**：OBO 后置的决策记录。
2. **调用方**：后续实现者与评审者。
3. **信任边界**：文档与实现的一致性。
4. **恶意输入最坏结果**：文档误导导致未经 ADR 引入 OBO（缓解：写明「引入前必须新立 ADR」）。
5. **失败是否泄露信息**：无。

## 范围外

- OBO 实现、委托凭据生命周期、principal propagation（需新 ADR）。

## 证据

- `docs/evidence/SLICE-181-obo-deferral.txt`
