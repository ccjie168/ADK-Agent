# SLICE-210 模型网关的预算执行接线

状态: gated
依据: PROGRESS 已知缺口第 9 条（共享 `BudgetTracker` 未与模型网关联账）。

## 意图

1. `serve-model-gateway` 构造 `PolicyModelGateway` 时传入一个进程内 `BudgetTracker`。当前没有传，
   所以注册表解析出的 `manifest.model_policy.budget_usd` 在这条生产路径上从未执行。
2. `build_rag_factory` 接受可选 `budgets`，调用方可以把同一个 tracker 交给嵌入网关与模型路径；
   不传时仍各用一个新的 tracker，行为不变。
3. 运维手册写明：模型网关的预算是进程内累计，多副本各自记账。

## 契约（先改）

- `docs/contracts/cli.md` 的 `serve-model-gateway` 一节补「请求策略的 `budget_usd` 由进程内
  `BudgetTracker` 累计执行，超限返回 403 `model_denied` 并写 `budget_exceeded` 审计；多副本各自记账」。

## 完成判据

- [x] 网关服务带 tracker -> `test_serve_model_gateway_enforces_budget`
- [x] 工厂接受注入的 tracker -> `test_build_rag_factory_shares_budget_tracker`
- [x] 全量门禁通过

## 反例

- 基线 `0a38c72`：`serve-model-gateway` 构造的网关 `budgets is None`，超限请求仍然成功，
  `test_serve_model_gateway_enforces_budget` 失败。
- 若 `build_rag_factory` 忽略传入的 tracker，`test_build_rag_factory_shares_budget_tracker` 失败。

## 5 问威胁建模

1. **数据**：每租户已花费的模型美元数。
2. **调用方**：模型网关的 HTTP 调用方与同进程的嵌入路径。
3. **信任边界**：注册表策略 → 网关进程内计数器。
4. **恶意输入最坏结果**：预算不执行时租户可以无限花费；共享范围过大时一个租户的嵌入花费
   误伤另一个租户。缓解：计数器按租户键控，只共享同一进程内的同一 tracker。
5. **失败是否泄露信息**：超限只返回 `model_denied` 与 `budget_exceeded` 审计，不含金额。

## 范围外

- 跨副本预算（需要共享存储，属 ADR 级决定）。
- 控制台 `GatewayLlm` 的 manifest 预算：合成策略只带 provider，不在本切片。
- `rag ingest`/`rag search` 一次性命令看不到历史花费，契约已注明。

## 证据

- `docs/evidence/SLICE-210-model-budget-wiring.txt`
