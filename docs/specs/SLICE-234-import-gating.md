# SLICE-234 导入路由权限

状态: gated
依据: 用户 2026-11-23 确认：基础角色不能发布 agent；术语表批量导入 admin+operator。

## 意图

1. `POST /api/import/agent` 挂 `registry.publish`（publisher + admin），基础角色不能再发布 agent。
2. `POST /api/import/terminology` 挂新的 `semantics.write` 能力（admin + operator），术语表批量导入
   收为运维角色；能力检查是 principal 解析后第一条语句（先于 config 404 与请求体解析）。
3. 新增能力 `semantics.write` 进 `_CAPABILITIES_ALL` 与 `_CAPABILITIES_OPERATOR`。

## 契约（先改）

- `docs/contracts/console.md`：`POST /api/import/terminology` 加「需要 `semantics.write` 能力」；
  `POST /api/import/agent` 加「需要 `registry.publish` 能力」；两者都注明检查先于配置 404 与请求体解析。
- 能力清单描述补 `semantics.write`。

## 完成判据

- [x] 术语表导入：缺 `semantics.write`（requester）403，先于 config 404 -> `test_import_terminology_requires_semantics_write`
- [x] agent 导入：缺 `registry.publish`（requester）403，先于 config 404 -> `test_import_agent_requires_registry_publish`
- [x] 能力清单含 `semantics.write`（admin+operator，publisher/base 无）-> `test_console_me.py` 更新
- [x] 全量门禁通过

## 反例

- 基线 `687465c`：`/api/import/terminology` 与 `/api/import/agent` 无能力检查，requester 也能写
  （terminology 未配置时 404，配置后 200/201）。加用例、未改实现时，requester 调用得 404 或 2xx，
  断言 403 失败。

## 5 问威胁建模

1. **数据**：术语表（业务词汇）与 agent 定义（manifest）。
2. **调用方**：控制台浏览器（Bearer token 鉴权后）。
3. **信任边界**：`semantics.write` admin+operator；`registry.publish` publisher+admin。
4. **恶意输入最坏结果**：基础角色发布任意 agent（越权发布）或批量篡改术语表。缓解：能力检查前置。
5. **失败是否泄露信息**：403 固定 `forbidden`，不泄露配置状态。

## 范围外

- 「业务用户逐条写术语表」的轻量入口（需要新端点，另行设计）。
- 只读面板可见性收紧（SLICE-235）。

## 证据

- `docs/evidence/SLICE-234-import-gating.txt`
