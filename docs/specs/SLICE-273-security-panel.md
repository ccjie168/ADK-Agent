# SLICE-273 安全合规面板（SecurityView）与接口残余修复

状态: gated
依据: ADR-0042（已接受）；SLICE-272 第二轮独立验证的 S1/S2/S3 残余

## 意图

交付 ADR-0042 的前端部分，同时修掉 SLICE-272 验证留下的三处诚实性与可达性缺口。

1. **接口残余**
   - `scans` 严格按 `docs/contracts/security_report.schema.json` 校验；缺字段、类型不符或出现未定义字段时返回 `null`，不再返回全 null 的对象。
   - 审计查询失败时 `audit.records` 为 `null` 并给固定错误码 `audit_unavailable`，不再把「后端宕机」显示成「审计为空」。
   - 凭据 store 抛 `ValueError`（租户名含 `/` 触发 `UnsafePath`）时按 `credential_store_unavailable` 处理，不再 500。
2. **安全面板** `web/src/views/SecurityView.vue`（`/security`，导航「安全」），按 `ops.read` 门控：
   四张卡片（审计 / 密钥 / 策略 / 扫描）；「校验审计链」按钮调 `?verify=1`；
   `scans` 为 null 时显示「未提供扫描报告」；服务端错误码映射为固定文案；无 `v-html`。

## 契约（先改）

`docs/contracts/console.md` 的 `GET /api/security`：

- `audit.records` 可为 `null`；查询失败时附 `error: "audit_unavailable"`，`last_event_at` 为 `null`。
- `keys.credentials.error` 取值 `credential_store_unavailable`（仅失败时出现）。
- `scans` 未配置、读不出或不符合 `security_report.schema.json` 时为 `null`。

## 完成判据

- [x] 审计查询异常时 `records` 为 null、`error` 为 `audit_unavailable`，响应 200 -> `test_security_reports_audit_unavailable`
- [x] 不符合 schema 的扫描报告按 null 处理 -> `test_security_ignores_an_off_schema_report`
- [x] 凭据 store 抛 `ValueError` 不导致 500，给固定错误码 -> `test_security_survives_an_unsafe_credential_tenant`
- [x] 深层嵌套报告解析溢出按 null 处理 -> `test_security_treats_a_deeply_nested_report_as_missing`
- [x] `notes` 类型不符按 null 处理 -> `test_security_ignores_a_report_with_wrong_notes_type`
- [x] 审计不可用时 `?verify=1` 不掩盖 `audit_unavailable` -> `test_security_keeps_audit_unavailable_after_verify`
- [x] 扫描报告只回传 `open`/`vulnerabilities` 两个计数，未知嵌套字段不回显 -> `test_security_drops_unknown_scan_counters`
- [x] 面板按 `ops.read` 门控 -> `test_security_view_requires_ops_read`
- [x] 面板含「校验审计链」，请求带 `verify=1` -> `test_security_view_verifies_the_audit_chain`
- [x] 服务端固定错误码在面板上有对应文案 -> `test_security_view_maps_fixed_error_codes`
- [x] 扫描报告缺失时显示「未提供扫描报告」 -> `test_security_view_shows_missing_scan_report`
- [x] 面板无 `v-html` -> `test_security_view_has_no_raw_html`
- [x] `/security` 路由与导航项存在 -> `test_security_route_is_registered`
- [x] `web/dist/` 重建且 `--full` 门禁通过

## 反例

实现前运行 `tests/test_console_security.py` 与 `tests/test_console_vue_security.py`：
新增的后端三条与前端六条全部失败（视图文件不存在、路由未注册；`records: 0`、全 null 的 scans、`ValueError` 直冒）。

## 5 问威胁建模

1. **数据**：审计元数据、key id 与计数、策略版本、扫描摘要；不返回密钥材料与事件内容。
2. **调用方**：`ops.read`（admin + operator）；`?verify=1` 的 10 秒超时与 60 秒缓存沿用 SLICE-272。
3. **信任边界**：扫描报告由运维写入，按 schema 严格校验；不符合即视为没有报告。
4. **恶意输入**：`?verify` 只认 `1`；扫描报告的超长/多余字段被拒绝；错误码固定，不回显服务端异常文本。
5. **失败是否泄露信息**：失败只给固定码；不返回链内容、密钥或租户路径。

## 范围外

- 非文件后端的链校验。
- 密钥轮换动作（仍走 CLI）。
- CI 扫描合并脚本（SLICE-274）。
- 视觉改造（SLICE-275 起的 Cloudflare 风格设计令牌与外壳）。

## 证据

- `docs/evidence/SLICE-273-security-panel.txt`
