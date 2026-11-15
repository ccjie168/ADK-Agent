# 安全审核操作说明

依据 ADR-0023。一个 ADR 的切片批次在 babysit 完成后、shipping 之前跑一次 CodeQL 全量审核。按批次触发，不按 ADR 文档签署日。

## 触发时机

满足以下全部条件时执行。

- 批次内的 PR 都到了 merge-ready，Babysit 已停。
- 批次 head 已确定，没有待推的修复。
- 还没有进入 Shipping。

## 步骤

1. 记录批次 head 与 commit 范围。
2. 手动触发扫描。
   ```bash
   gh workflow run codeql.yml --ref <branch>
   gh run list --workflow codeql.yml --branch <branch> --limit 1
   gh run watch <run-id>
   ```
3. 读取开放告警。
   ```bash
   gh api "repos/<owner>/<repo>/code-scanning/alerts?state=open&ref=refs/heads/<branch>&per_page=100"
   ```
   Security 页面的告警与这个接口一致。
4. 逐条分诊。每条标为 fixed、accepted 或 dismissed。
5. 写证据文件 `docs/evidence/security/ADR-XXXX-codeql.txt`。
6. 结论是 PASS 或 PASS+NOTES 时，批次才进入 shipping。

## 分诊规则

- HIGH 与 CRITICAL 在批次内修复，或写明理由与到期日接受，格式参考 `.trivyignore.yaml`。
- 涉及认证、租户隔离、密钥、审批与能力清单的发现，不由单人 dismiss。
- dismiss 必须写具体反证，例如“输入已在 `_SAFE_NAME` 校验，调用点在第 N 行”。只写 false positive 不算。
- 不为了安静而改代码。找不到反证时保留告警，标为 PASS+NOTES 交给批次负责人。

## 证据模板

```text
ADR-XXXX CodeQL 安全审核

日期: YYYY-MM-DD
批次 head: <commit>
commit 范围: <base>..<head>
workflow run: <url>
CodeQL: v4 / security-extended / Python

发现统计
  critical: N
  high: N
  medium: N
  low: N

分诊
  <rule-id> <path>:<line> fixed|accepted|dismissed <一句理由> [到期日]

接受风险
  <rule-id> <理由> <到期日>

结论: PASS | PASS+NOTES | FAIL
```

## 边界

CodeQL 只做静态分析。运行时授权、RLS、审批绕过与能力清单越权仍由测试与人工威胁模型覆盖。安全审核不能替代这两者。
