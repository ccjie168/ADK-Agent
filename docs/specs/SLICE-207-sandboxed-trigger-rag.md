# SLICE-207 沙箱化触发的检索接线

状态: gated
依据: PROGRESS 已知缺口第 9 条、2026-11-21 复盘第七节第 3 条。

## 意图

1. `execution_tier=sandboxed` 的触发不再绕过检索：运行前按 pinned manifest 做一次预取，把固定
   边界块拼到传给沙箱的输入前面，并写 `rag.retrieve` 审计。
2. 检索失败按 `RagContext` 的 `on_error` 处理：`deny` 让本次触发失败，返回 `rag_unavailable`
   （500）；`degrade` 记审计后不带上下文继续。
3. 配额拒绝时不检索（预取放在配额预留之后、沙箱运行之前）。
4. 审计 `agent.run` 的 `args_hash` 仍取原始输入，不含检索块。

## 契约（先改）

- 触发服务的错误码增加 `rag_unavailable`（500），写进 `docs/contracts/cli.md` 的触发服务一节与
  运维手册；manifest 与 `rag.retrieve` 事件形状不变。

## 完成判据

- [x] 沙箱触发把检索块拼到输入前 -> `test_sandboxed_trigger_injects_retrieval`
- [x] 检索失败返回 500 `rag_unavailable` 且不调用沙箱 -> `test_sandboxed_trigger_denies_when_retrieval_fails`
- [x] 既有触发行为与审批拒绝不变（全量用例）
- [x] 全量门禁通过

## 反例

- [x] 基线 `25aafbe` 加新用例：`2 failed, 23 passed`（沙箱收到原始输入；检索失败仍返回 200）。
- [x] 若把预取放到配额检查之前，配额拒绝路径会多一次检索与审计。

## 5 问威胁建模

1. **数据**：检索上下文、pinned manifest 的 `rag` 配置与审计事件。
2. **调用方**：webhook/调度触发。
3. **信任边界**：注册表 pinned 记录 → 沙箱进程输入。
4. **恶意输入最坏结果**：检索失败被静默忽略，沙箱拿到空上下文继续跑；或租户越权取到别人的片段。
   缓解：失败按 `on_error` 显式处理并写审计；ACL 在 `PgVectorRagService` 内按 principal 执行；
   主体租户来自触发定义。
5. **失败是否泄露信息**：错误只回 `rag_unavailable`；审计只记计数、状态与延迟，不含片段。

## 范围外

- 沙箱平台本身（POSIX-only）在 Windows 上的运行。
- 预取结果的重排与引用拼接。

## 证据

- `docs/evidence/SLICE-207-sandboxed-trigger-rag.txt`
