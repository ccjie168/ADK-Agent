# SLICE-074 评测报告集中存储

状态: merged
依据: ADR-0009，SLICE-071，SLICE-072，`docs/contracts/registry_service.md`。

## 意图（要什么，不写怎么写）

发布带评测报告时，`--registry-url` 目前只能拒绝 `--eval-report`，因为报告还写在本地目录。这一刀把报告放进注册表服务的共享存储，让发布、控制台评测面板和多副本看到同一份报告。

- 新增 `PostgresEvalReportStore`，表 `adk_eval_reports(tenant, agent_id, version, report jsonb, stored_at)`，同版本同内容幂等，不同内容抛 `EvalReportConflict`。
- 注册表服务新增 `GET`/`PUT /v1/agents/{tenant}/{id}/{version}/eval`，版本必须已发布，租户绑定同其他端点。
- `serve-registry` 总是为报告配置 Postgres 存储，不需要额外参数。
- 新增 `HttpEvalReportStore` 实现 `EvalReportStore` 端口。
- `publish --registry-url --eval-report` 在记录发布后上传报告，再上传工件字节。
- 控制台给了 `--registry-url` 时，评测面板改用 HTTP 报告存储。

## 新增文件

- `src/adk_agent/registry/reports_postgres.py`
- `tests/registry/test_eval_reports_postgres.py`
- `tests/registry/test_registry_eval_service.py`
- `tests/registry/test_registry_eval_client.py`
- `docs/evidence/SLICE-074-central-eval-reports.txt`

## 修改文件

- `src/adk_agent/registry/service.py`、`client.py`、`__init__.py`
- `src/adk_agent/cli.py`
- `docs/contracts/registry_service.md`、`docs/contracts/cli.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
adk_eval_reports(
  tenant text, agent_id text, version text,
  report jsonb NOT NULL, stored_at timestamptz NOT NULL,
  PRIMARY KEY (tenant, agent_id, version)
)

PostgresEvalReportStore(url)
  put(tenant, id, version, report) -> EvalReport | EvalReportConflict
  get(...) -> EvalReport | None
  has(...) -> bool

HttpEvalReportStore(base_url, *, auth_token, client, timeout)
```

## 完成判据（可执行）

- [x] Postgres 报告往返 -> `tests/registry/test_eval_reports_postgres.py::test_live_roundtrip`
- [x] 同内容幂等、不同内容冲突 -> `::test_live_conflict`
- [x] 缺失返回 None/False -> `::test_live_missing`
- [x] 服务 PUT/GET 报告 -> `tests/registry/test_registry_eval_service.py::test_put_then_get`
- [x] 版本不存在 404 -> `::test_version_required`
- [x] 报告冲突 409 -> `::test_conflict`
- [x] 跨租户 403 -> `::test_cross_tenant_forbidden`
- [x] 非法报告 400 -> `::test_invalid_report`
- [x] HTTP 报告客户端往返与缺失 -> `tests/registry/test_registry_eval_client.py::test_roundtrip_and_missing`
- [x] 发布带报告走 HTTP -> `tests/test_registry_url_wiring.py::test_publish_uploads_eval_report`
- [x] `serve-registry` 装配报告存储 -> `tests/test_cli_registry_service.py::test_builds_eval_store`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from adk_agent.registry import PostgresEvalReportStore` -> 当前 `ImportError`
- [x] 反例 2：服务 `PUT .../eval` -> 当前 404/405
- [x] 反例 3：`publish --registry-url --eval-report` -> 当前退出 1

## 契约（如涉及对外接口）

已先改 `docs/contracts/registry_service.md` 与 `docs/contracts/cli.md`。

## 5 问威胁建模（10 分钟）

1. **数据**：评测报告、租户、版本、分数与门禁结论。
2. **调用方**：发布脚本、控制台、运维。
3. **信任边界**：HTTP 到服务；服务到 Postgres；发布者到报告内容。
4. **恶意输入最坏结果**：跨租户写报告（缓解：版本存在校验加租户绑定）；篡改已发布报告（缓解：同版本冲突拒绝覆盖）；超大报告（缓解：请求体上限待定，沿用 8 MiB 级限制）；用报告冒充评测结论（缓解：报告不是签名对象，仍以发布者身份与审计为准）。
5. **失败是否泄露信息**：错误码固定，不回显报告内容或 DSN。

## 范围外

- 报告签名与来源证明。
- 报告历史与多份报告。
- 报告驱动的自动回滚。
- 控制台以外的报告消费方。

## 证据

- 反例红: `docs/evidence/SLICE-074-central-eval-reports.txt` 的 red 段
- 实现后绿: 同文件 green 段
- 实机: 同文件 live 段，真 Postgres 与两个进程
