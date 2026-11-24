# ADR-0042 安全合规聚合视图（阶段 3）

状态: Accepted   日期: 2026-11-24   签字: Jie CAO（会话确认，含下述两项修订）

## 背景

ADR-0041 阶段 3 的目标是「安全合规聚合视图（诉求 5）：审计完整性、扫描、密钥轮换、策略概览」。
现状是这些信息分散在：

- **审计**：`GET /api/audit` 只返回事件列表；链完整性只能通过 CLI `verify-audit`
  （`verify_audit_file` / `verify_audit_database`）检查。
- **密钥**：凭据 KEK 的 active id 只在 `LocalKeyBackend` 内部；轮换靠 CLI `credentials rewrap`；
  审计签名 keyring（`ADK_AUDIT_SIGNING_KEY` / `ADK_AUDIT_KEYRING`）没有只读视角。
- **策略**：`GET /api/policy` / `PUT /api/policy` 已有。
- **扫描**：CodeQL、pip-audit、Trivy 都在 CI 里跑，结果不进运行时。

运维现在要切三四个地方（面板 + CLI + CI 日志）才能回答「审计链是否完整、密钥是否需要轮换、
最近一次扫描结果如何」。

## 决定

### 1. 一个只读聚合接口

新增 `GET /api/security`，能力 `ops.read`（与总览/配额/RAG 一致，admin + operator 可见），返回四块：

```json
{
  "audit": {
    "backend": "file|http|db|none",
    "records": 1234,            // 有计数来源时给出，否则 null
    "last_hash": "…",           // 最近一条记录的 hash，无可读来源时 null
    "verified": true|null,      // 仅在 ?verify=1 且后端可校验时给出
    "error": "chain_broken"     // 校验失败时的固定错误码，不给记录内容
  },
  "keys": {
    "audit_signing": {"active": "k2", "kids": ["k1", "k2"], "legacy": false},
    "credentials": {"active_key_id": "kek-2", "by_key_id": {"kek-1": 3, "kek-2": 5},
                    "needs_rewrap": 3}
  },
  "policy": {"version": "v3", "bindings": 4},
  "scans": {"generated_at": "…", "codeql": {"open": 0}, "dependencies": {"vulnerabilities": 0}} | null
}
```

要点：

- **`?verify=1` 才做链校验**。默认请求只返回后端类型与最近记录元数据，避免每次打开面板都全链扫描；
  校验请求由面板上的「校验审计链」按钮触发。**校验是有界的**：超过 10 秒返回固定码 `verify_timeout`，
  同一审计后端 60 秒内的重复校验复用上次结果，避免 operator 连点拖垮服务端。
- **绝不返回密钥材料**：只给 key id、计数与布尔状态。凭据统计来自现有 `CredentialStore.list`，
  按 `secret_key_id` 分桶，`needs_rewrap` = `secret_key_id != active_key_id` 且已有 `wrapped_secret` 的条数。
- **扫描结果来自文件**：新增 `console --security-report PATH`（JSON，见 `docs/contracts/security_report.schema.json`），
  CI 或运维把聚合结果写进去；未配置时 `scans: null`。不在运行时重跑扫描器。
- 审计后端读取失败、keyring 未配置等一律返回 `null` 字段 + 固定 error 码，不 500。

### 2. 契约先改

`docs/contracts/console.md` 增加 `GET /api/security` 一节；新增 `docs/contracts/security_report.schema.json`
定义扫描报告文件形状（`generated_at`、`codeql.open`、`dependencies.vulnerabilities`、可选 `notes`）。

### 3. 前端

`web/src/views/SecurityView.vue`（`/security`，导航「安全」）按 `ops.read` 门控：
四张卡片（审计 / 密钥 / 策略 / 扫描），点「校验审计链」调 `?verify=1` 并显示结果；
`scans` 为 null 时显示「未提供扫描报告」；无 `v-html`。

### 4. 切片顺序

- SLICE-272：`GET /api/security`（`?verify=1`）+ 契约 + schema + 单测（含「不给密钥材料」断言）。
- SLICE-273：`SecurityView.vue` + 路由 + 导航 + 源码检查测试。
- SLICE-274（**必做**）：`scripts/security_report.py` 把 CI 的扫描结果（gate 的 deps 步、CodeQL 导出）
  汇总成 schema 文件，否则面板的「扫描」卡永远为空、等于摆设。

## 备选与否决

- **面板里直接跑 pip-audit / CodeQL**：运行时无这些工具与数据库，且扫描应发生在构建流水线。
  否决；改为读取 CI 产物。
- **每次打开面板就全链校验**：审计链可达数十万条，打开面板的延迟不可接受。否决；改为按需触发。
- **新增 `security.read` 能力**：能力词表刚在阶段 1 扩过，阶段 3 的读路径与总览同属运维视角，
  复用 `ops.read` 足够；如需更细粒度，后续单独 ADR。
- **返回密钥指纹/前缀**：会缩窄暴力空间，否决；只给 id。

## 后果

- 运维在一个页面里回答四个问题；扫描结果仍依赖 CI 产物文件，缺失时显式为 `null`（诚实显示而非假装通过）。
- 审计链校验是显式动作，费用可控；校验失败会以固定错误码呈现，不泄露记录内容。
- 新增一个可选启动参数与一个契约文件；无新依赖。

## 风险

- `--security-report` 文件由外部写入，内容按 schema 校验后只做展示；解析失败按 `scans: null` 处理。
- 凭据统计需要遍历凭据 store；与凭据规模线性，面板为人工触发，可接受。

## 确认记录（2026-11-24 会话确认）

1. 接受「`ops.read` + 按需 `?verify=1`」的接口形态，**并采纳修订：校验有界（10 秒超时 + 60 秒结果缓存）**。
2. 接受「扫描结果通过 `--security-report` 文件由 CI 提供」，不在运行时重跑扫描器；
   **并采纳修订：SLICE-274 的汇总脚本由「可选」改为必做**。
3. 接受分片顺序 272 → 273 → 274。
