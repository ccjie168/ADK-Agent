# SLICE-147 spec 用例名校验加固与合同陈旧描述修正

状态: gated
依据: SLICE-146 的验证代理留下三个非阻断缺口；另有一条 `sandbox.md` 的陈旧描述与工具中介帧矛盾。

## 意图

1. 引用识别支持四种写法：裸名、带括号、带路径前缀、带路径与括号。
2. 用 AST 发现测试定义：不再把字符串里的 `def test_...` 当成真实用例，并纳入 `Test*` 类的方法。
3. 历史 spec（编号小于 146）不做引用校验：它们是已合并切片的记录，保留当时的引用；
   SLICE-146 起的新切片必须引用真实用例。
4. 修正 `docs/contracts/sandbox.md` 里“工具调用不中转”的陈旧描述，改为工具调用经父进程中转。
5. 补 `main()` 接线用例：防止它退回成不传测试名集合而静默关闭校验。

## 契约（先改）

- `docs/contracts/sandbox.md` 的模型中介段落先改。
- 门禁 specs 步骤的校验范围写入 `docs/guides/slice-checklist.md`。

## 完成判据

- [x] 带路径与括号的引用被识别并校验 -> `test_reference_variants_resolve`
- [x] 字符串里的假定义不算用例，类方法算用例 -> `test_defined_tests_uses_the_ast_not_strings`
- [x] `main()` 确实把测试名集合传进校验 -> `test_main_flags_unknown_references`
- [x] 历史 spec 不做引用校验 -> `test_reference_floor_exempts_historical_specs`
- [x] `sandbox.md` 与工具中介帧一致（人工复核）
- [x] 全量门禁通过

## 反例

- [x] 基线只认裸名，带路径与括号的不存在用例名写进 spec 仍通过
- [x] 基线把字符串里的测试函数定义当成用例，校验被假定义绕过

## 5 问威胁建模

1. **数据**：spec 文本与测试定义，不含敏感数据。
2. **调用方**：提交切片的开发者与门禁。
3. **信任边界**：无；只读仓库文件。
4. **恶意输入最坏结果**：虚假用例名进入 spec 制造虚假证据（缓解：门禁失败）；校验被静默关闭
   （缓解：`main()` 接线用例与 AST 用例）。
5. **失败是否泄露信息**：只输出文件名与缺失的用例名。

## 范围外

- 校验用例是否被收集、是否通过；这里只保证名字存在。
- 回溯修正历史 spec 的旧引用。

## 证据

- `docs/evidence/SLICE-147-spec-check-hardening.txt`
