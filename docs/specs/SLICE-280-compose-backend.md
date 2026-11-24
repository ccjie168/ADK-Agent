# SLICE-280 compose 后端：模板、预览与一键发布

状态: gated
依据: ADR-0043（Accepted，2026-11-24 / 2026-11-25 会话确认）

## 意图

给控制台装上 ADR-0043 决定的发布路径：

1. **能力**：新增 `registry.compose`（admin + publisher），`tests/test_console_me.py` 的两处
   期望集合同步更新（已获确认）；前端 `web/src/api/capabilities.ts` 跟随（`test_console_vue_roles.py`
   按集合比对，自动覆盖）。
2. **端点**：
   - `GET /api/compose/templates`（`registry.publish`）返回 `{"configured": bool, "templates": [...]}`；
   - `POST /api/compose/preview`（`registry.publish`）用 `build_composed` 渲染，返回 manifest、
     `agent.py` 与工件 digest，不发布、不签名、不需要密钥；
   - `POST /api/compose`（`registry.compose`）用控制台专用密钥签名、发布并入库。
3. **密钥**：`console` 新增 `--compose-key/--compose-key-id/--compose-builder-key/--compose-builder-key-id`，
   四者必须同时给出；只给一部分启动退出 2，私钥不可读/非法退出 1；全部缺失时发布端点返回 404
   `compose_not_configured`，其余功能不受影响。密钥只从文件读，与审计/凭据密钥分离。
4. **审计**：发布写 `agent.compose`，记录模板 id、租户/Agent/版本与工件 digest；
   `AuditEvent` 新增可选的 `template_id` 字段（默认不序列化），契约随导出脚本重新生成；
   不记录指令原文。
5. **评测门禁**：沿用 `enforce_eval_gate`。

## 契约（先改）

- `docs/contracts/console.md`：三个端点的请求/响应与错误码
  （`compose_invalid`、`tenant_forbidden`、`compose_not_configured`、`registry_not_configured`、
  `registry_conflict`、`artifact_store_unavailable`、`registry_unavailable`）。
- `docs/contracts/cli.md`：四个 compose 密钥参数与组合规则。
- `docs/contracts/audit_event.schema.json`：新增可选 `template_id`（由 `scripts/export_contracts.py` 生成）。
- `docs/contracts/compose.md`：补控制台入口一段，指向 `console.md`。

## 完成判据

- [ ] 模板列表要求 `registry.publish` -> `test_compose_templates_require_publish_capability`
- [ ] 预览渲染 manifest/agent.py/digest -> `test_compose_preview_renders_the_bundle`
- [ ] 非法参数返回 400 `compose_invalid` -> `test_compose_preview_rejects_bad_parameters`
- [ ] 预览跨租户返回 403 `tenant_forbidden` -> `test_compose_preview_forbids_a_foreign_tenant`
- [ ] 预览不依赖签名密钥 -> `test_compose_preview_works_without_signing_keys`
- [ ] 发布要求 `registry.compose` -> `test_compose_publish_requires_compose_capability`
- [ ] 未配置密钥返回 404 `compose_not_configured` -> `test_compose_publish_returns_compose_not_configured`
- [ ] 未配置注册表返回 404 `registry_not_configured` -> `test_compose_requires_a_registry`
- [ ] 发布写入签名工件且注册表记录可验证 -> `test_compose_publish_stores_a_signed_artifact`
- [ ] 审计记录 `agent.compose` 且不含指令原文 -> `test_compose_audit_omits_the_instruction`
- [ ] 发布跨租户返回 403 -> `test_compose_publish_rejects_a_foreign_tenant`
- [ ] publisher 角色获得 `registry.compose` -> `test_compose_capability_reaches_publisher`
- [ ] 只给部分密钥参数启动退出 2 -> `test_console_rejects_partial_compose_keys`
- [ ] 私钥不可读或非法启动退出 1 -> `test_console_rejects_an_invalid_compose_key`
- [ ] `--full` 门禁通过，`web/dist/` 随能力常量重建

## 反例

实现前三个端点不存在（404），`/api/me` 的 publisher 能力集合没有 `registry.compose`，
`console` 不认识四个新参数（argparse 退出 2）；上述用例在旧代码上失败。

## 5 问威胁建模

1. **数据**：模板参数、生成的 manifest 与 `agent.py`、工件摘要；私钥只在服务端内存。
2. **调用方**：模板与预览 `registry.publish`、发布 `registry.compose`（admin + publisher）；
   非 admin 只能操作自身租户。
3. **信任边界**：模板固定为 `single-llm`，参数用 `repr` 嵌入；指令长度 ≤4000；不接受任意源码。
4. **恶意输入**：请求体字段逐项校验类型；非法参数 400；跨租户 403；未配置 404；不返回异常原文。
5. **失败是否泄露信息**：固定错误码与固定文案；审计不含指令；响应不含私钥或宿主路径。

## 范围外

- 前端向导（SLICE-281）。
- 密钥轮换与托管细节（运维手册另行补充）。
- 新模板或任意 ZIP 上传。

## 证据

- `docs/evidence/SLICE-280-compose-backend.txt`
