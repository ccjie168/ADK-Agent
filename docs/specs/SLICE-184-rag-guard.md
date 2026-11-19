# SLICE-184 提示注入防护与低置信度拒答

状态: gated
依据: ADR-0032（Accepted 2026-11-19）决定 4 / slice 3：检索内容进上下文前做注入检测，无来源或低置信度
不得生成确定性业务结论。本切片落 RAG 守卫并接入结构化检索。

## 意图

1. `src/adk_agent/rag/guard.py` 新增 `detect_prompt_injection(text)`：按内置注入模式（正则）检测。
2. 同文件新增 `RagGuard`：`min_confidence` 阈值 + 注入检测，`filter(citations)` 丢弃低置信度或含注入的引用。
3. `InMemoryRagService` 增加可选 `guard` 参数，`retrieve` 末尾应用守卫。
4. 从 `adk_agent.rag` 导出 `RagGuard`/`detect_prompt_injection`。

## 契约（先改）

- 无对外 schema 变更（实现级守卫）。

## 完成判据

- [ ] 注入文本被检出 -> `test_detect_prompt_injection`
- [ ] 低置信度被过滤 -> `test_guard_filters_low_confidence`
- [ ] 注入引用被过滤 -> `test_guard_filters_injection`
- [ ] 正常引用保留 -> `test_guard_keeps_valid_citation`
- [ ] 服务应用守卫 -> `test_service_applies_guard`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上无 `RagGuard`/`detect_prompt_injection`

## 5 问威胁建模

1. **数据**：检索引用的片段与置信度。
2. **调用方**：模型上下文组装（未来）。
3. **信任边界**：检索内容到模型上下文。
4. **恶意输入最坏结果**：注入片段进入上下文劫持模型（缓解：进上下文前注入检测 + 过滤）。
5. **失败是否泄露信息**：无新错误面。

## 范围外

- 真实 SQL/API 后端（后续）。
- 向量后端独立 ADR。
- 更复杂的注入检测模型（后续）。

## 证据

- `docs/evidence/SLICE-184-rag-guard.txt`
