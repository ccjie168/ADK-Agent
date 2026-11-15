# ADR-0023 安全审核通道与 CodeQL

状态: Accepted   日期: 2026-11-16   签字: Jie CAO（会话确认）

## 背景

现有门禁在每次提交与每个 PR 上跑 Bandit、pip-audit、Trivy、detect-secrets 与完整测试，另有 CycloneDX SBOM 与带到期日的接受风险清单。缺口是深层 SAST 与 DAST。Bandit 只覆盖常见 Python 反模式，看不懂数据流。

平台真正的风险不在语法模式。租户隔离、RLS、审批绕过、能力清单越权由测试与人工威胁模型覆盖。扫描器是补充，不是替代。

仓库是 public，GitHub 对公共仓库免费提供 CodeQL code scanning。这是当前成本最低的深层 SAST，Python 的污点与数据流分析强于 SonarQube。

## 决定

1. **CodeQL 单腿起步。** 只启用 CodeQL，语言为 Python，查询集 `security-extended`。触发点为指向 master 的 pull request、master 的 push、每周一凌晨的定时扫描，以及手动触发。PR 上先作为观察项，不立即设为必需检查；连续两周基线干净后，再把 CodeQL 加入分支保护的必需检查。
2. **每个 PR 的阻塞门不变。** `scripts/check.py --full --strict` 仍是唯一 PR 阻塞门。CodeQL 不与它合并，也不替代它。
3. **ADR 批次安全审核。** 一个 ADR 的切片批次在 babysit 完成后、进入 shipping 前，必须对批次 head 跑一次全量 CodeQL，逐条分诊，并写证据文件。证据文件路径是 `docs/evidence/security/ADR-XXXX-codeql.txt`。没有 PASS 或 PASS+NOTES 结论，不进入 shipping。
4. **证据格式。** 文件写明日期、commit 范围、workflow run 链接、按严重度统计的发现数、逐条分诊结论、带到期日的接受风险，以及 PASS、PASS+NOTES 或 FAIL。FAIL 必须点名未解决的 HIGH 或 CRITICAL。
5. **分诊规则。** HIGH 与 CRITICAL 在批次内修复，或按 `.trivyignore.yaml` 的方式写明理由与到期日接受。dismiss 必须有具体反证，不能为了安静而改代码。涉及认证、租户隔离、密钥与审批的发现，不由单人 dismiss。
6. **范围外。** DAST、SonarQube、Semgrep 与 git 历史密钥扫描不在本 ADR 内。DAST 需要一套带测试租户的运行栈，另立 ADR 或切片。SonarQube 只在有合规报告或质量仪表盘需求时再评估。
7. **Fork 保护。** 来自 fork 的 PR 不给 `security-events: write`，工作流跳过 CodeQL。维护者合入前用 `workflow_dispatch` 手动跑一次。来自本仓库分支的 PR 正常扫描。

## 备选与否决

- **SonarQube 作为主 SAST**：Python 污点分析弱于 CodeQL，需要自托管或付费，主要价值在质量门与仪表盘；暂缓。
- **同时上 CodeQL、SonarQube 与 Semgrep**：三套告警与三套分诊，团队会被噪音拖住；否决。
- **每个 PR 跑 DAST**：依赖运行栈与测试数据，速度慢，误报多；否决。
- **立即把 CodeQL 设为必需检查**：首次全量扫描的基线未清，会卡住所有 PR；改为先观察再提升。
- **只在发布镜像时跑 CodeQL**：太晚，ADR 批次的问题应在 shipping 前暴露；否决。

## 后果

- CI 增加一次 CodeQL 分析，公共仓库不额外计费，但会占用 runner 时间。
- 首次全量扫描预计会有一批发现，需要一次集中分诊。分诊负责人不固定时，安全门会停滞。
- CodeQL 看不到运行时授权与租户隔离，测试仍是这些风险的主要控制。
- 安全证据成为 release readiness 的一部分，与现有的全量门禁并列。
- 公共仓库的 code scanning 告警对公众可见，这是可接受的透明度，也意味着 dismiss 理由要经得起看。

## 实现

- `.github/workflows/codeql.yml`：CodeQL Python 工作流，action 固定到 commit SHA。
- `docs/guides/security-review.md`：ADR 批次安全审核的操作步骤与证据模板。
- 不占切片编号。

## 确认记录

2026-11-16 会话确认先启用 CodeQL 单腿，DAST 与 SonarQube 暂缓；安全审核放在 ADR 批次 merge-ready 之后、shipping 之前，CodeQL 在 PR 上先观察，再提升为必需检查。
