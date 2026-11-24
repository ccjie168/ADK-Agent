# SLICE-274 CI 扫描汇总脚本

状态: gated
依据: ADR-0042 的必做修订；`docs/contracts/security_report.schema.json`

## 意图

安全面板的「扫描」卡依赖 `console --security-report PATH`，但此前没有任何东西生成这个文件，
面板永远是「未提供扫描报告」。本切片交付 `scripts/security_report.py`：

- 读 CodeQL SARIF 与 `pip-audit --format json` 的结果；
- 统计**未压制**的 CodeQL 结果数（只有 `status` 为 `accepted` 或未给 status 的压制算关闭，`rejected`/`underReview` 仍算开放）与依赖漏洞数；
- 写出一份严格符合 `docs/contracts/security_report.schema.json` 的 JSON（`generated_at` 为 UTC、秒级、`Z` 结尾）；
- 输入缺失、形状不对或输出不可写时退出 2，不写半成品文件；成功时用 `tempfile.mkstemp` 在同目录写临时文件再原子替换，失败清理临时文件。

不在运行时重跑扫描器；CI 或运维在构建流水线里跑本脚本。

## 契约（先改）

输出遵循既有 schema，不改字段：

```json
{"generated_at": "2026-11-25T00:00:00Z", "codeql": {"open": 0}, "dependencies": {"vulnerabilities": 2}}
```

`notes` 可选，仅在传入时出现。

用法：

    python scripts/security_report.py \
        --codeql-sarif codeql.sarif \
        --pip-audit-json pip-audit.json \
        --out security-report.json [--notes "nightly"]

## 完成判据

- [x] 只有 accepted（或缺 status）的压制算关闭，rejected/underReview 仍开放，跨 run 累加 -> `test_codeql_counts_only_accepted_suppressions`
- [x] 缺失 `results` 按 0 -> `test_codeql_tolerates_missing_results`
- [x] 非法 SARIF 形状报错 -> `test_codeql_rejects_bad_result_shapes`
- [x] 非 SARIF 文档报错 -> `test_codeql_rejects_a_non_sarif_document`
- [x] pip-audit 的列表与新字典两种布局都支持 -> `test_dependencies_accept_both_pip_audit_layouts`
- [x] 依赖数据的非法形状报错 -> `test_dependencies_reject_bad_shapes`
- [x] 报告字段、时间格式与可选 notes 符合契约 -> `test_build_report_matches_the_contract`
- [x] `notes` 为空时省略 -> `test_build_report_omits_notes_when_empty`
- [x] 非 UTC 时间转换到 UTC -> `test_build_report_converts_to_utc`
- [x] 负数与布尔计数被拒绝 -> `test_build_report_rejects_negative_and_boolean_counts`
- [x] 端到端写出文件 -> `test_main_writes_the_report`
- [x] 输入缺失退出 2 且不写文件 -> `test_main_returns_2_for_a_missing_artifact`
- [x] 输出不可写退出 2 -> `test_main_returns_2_when_output_cannot_be_written`
- [x] 输出名称为空（如 `--out .`）也退出 2，且不留临时文件 -> `test_main_returns_2_for_an_empty_output_name`
- [x] 畸形/极深 JSON 退出 2 且不写文件 -> `test_main_returns_2_for_unusable_json`

## 反例

实现前 `scripts/security_report.py` 不存在：测试模块在导入阶段抛 `FileNotFoundError`，pytest 记为 1 个 collection error，用例并未逐条运行。这是本切片的真实红灯形态，不假装逐条变红。

## 5 问威胁建模

1. **数据**：公开的扫描计数与时间戳；不读取或输出漏洞详情、代码片段与凭据。
2. **调用方**：CI 或运维在构建机上运行；不暴露网络端口。
3. **信任边界**：SARIF 与 pip-audit JSON 是构建产物，按结构校验后只取计数。
4. **恶意输入**：超大/畸形 JSON 报错退出，不写文件；计数只接受非负整数（布尔拒绝）；
   输出先写临时文件再原子替换，失败清理临时文件并退出 2。
5. **失败是否泄露信息**：错误只说明哪个输入不可读或形状不对，不回显内容。

## 范围外

- 把脚本接进 GitHub Actions（需要流水线改动与产物传递，另行切片）。
- Trivy 镜像扫描与 SBOM 的汇总。
- 运行时重跑扫描器。

## 证据

- `docs/evidence/SLICE-274-security-report.txt`
