# SLICE-146 spec 用例名可执行校验与切片检查表

状态: gated
依据: 会话要求“写提示词不如写可运行的验证实例”。SLICE-144/145 的验证轮次暴露了 spec 引用不存在的用例名、文档数字陈旧、示例不可执行等问题。

## 意图

1. `scripts/check_specs.py` 在原有章节检查之外，校验活跃 spec 里反引号引用的 `test_*` 名字必须真实存在于 `tests/`；`状态: merged` 的 spec 跳过。
2. 修正现存唯一失效引用（SLICE-137 的旧用例名已改为实际用例）。
3. 新增 `docs/guides/slice-checklist.md`：切片顺序、已被自动化固化的检查、提交前人工检查、工具约定与 stop list。
4. `CLAUDE.md` 的切片流程指向该检查表，并声明用例名校验已由 `scripts/check_specs.py` 固化。

## 契约（先改）

- 无对外接口变化；门禁的 specs 步骤多一条失败条件。

## 完成判据

- [x] 引用了不存在的用例名会让 specs 步骤失败 -> `test_unknown_test_reference_is_rejected`
- [x] 引用真实用例名通过 -> `test_known_test_reference_passes`
- [x] `状态: merged` 的历史 spec 跳过用例名校验 -> `test_merged_specs_skip_the_reference_check`
- [x] 缺章节仍然报错 -> `test_missing_sections_are_reported`
- [x] 检查表文档存在并覆盖顺序、自动化检查、人工检查、工具约定与 stop list -> `test_slice_checklist_covers_the_required_sections`
- [x] 全量门禁通过

## 反例

- [x] 基线 `check_specs.py` 只查章节；把不存在的用例名写进 spec 仍然通过（SLICE-137 修前的旧名就是一例）
- [x] 删掉检查表会让 `test_slice_checklist_covers_the_required_sections` 失败；删掉 CLAUDE.md 的指向会让 `test_claude_md_links_the_checklist` 失败

## 5 问威胁建模

1. **数据**：spec 文本与测试名，不含敏感数据。
2. **调用方**：提交切片的开发者与门禁。
3. **信任边界**：无；校验只读仓库文件。
4. **恶意输入最坏结果**：spec 引用不存在的用例制造虚假证据（缓解：门禁失败）。
5. **失败是否泄露信息**：只输出缺失的用例名与 spec 文件名。

## 范围外

- 校验 evidence 文件里的用例名（历史记录可能保留旧名）。
- 校验文档代码块可执行（由 `tests/test_install_guide.py` 逐切片守卫）。

## 证据

- `docs/evidence/SLICE-146-spec-test-references.txt`
