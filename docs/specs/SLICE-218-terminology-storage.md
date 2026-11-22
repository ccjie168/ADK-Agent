# SLICE-218 术语层存储

状态: gated
依据: ADR-0038 MVP 第 2 项（术语层存储，registry 双后端）。

## 意图

1. 定义 `ConceptSchemeStore` 端口（`put`/`get`/`list`），存整个 `ConceptScheme`，按
   `(tenant, scheme_id)` 键控；tenant 是存储键，不在 `ConceptScheme` 模型里。
2. 两个实现：文件后端 `FileConceptSchemeStore`（`safe_join` + 原子覆盖），Postgres 后端
   `PostgresConceptSchemeStore`（`LazyPool` + jsonb + upsert）。租户隔离靠应用层 `WHERE tenant`
   过滤，MVP 不引入 RLS（与 `PostgresTriggerStore` 一致）。
3. `put` 是 upsert：同 `(tenant, scheme_id)` 覆盖，术语表是声明式可更新的，不做 conflict。
4. 存储不可用（坏 DSN、驱动缺失）统一映射 `ConceptSchemeStoreUnavailable`。

## 契约（先改）

- `docs/contracts/semantics.md` 新增「存储」一节，记录端口方法、键、upsert 语义与租户隔离。

## 完成判据

- [x] 文件后端写读往返 -> `test_file_store_put_get_roundtrip`
- [x] 同键 upsert 覆盖 -> `test_file_store_upsert_replaces_same_scheme`
- [x] 租户隔离 -> `test_file_store_isolates_tenants`
- [x] 缺失返回 None -> `test_store_missing_scheme_returns_none`
- [x] Postgres 后端往返 -> `test_postgres_store_roundtrip`（live，需 `TEST_POSTGRES_URL`）
- [x] 全量门禁通过

## 反例

- 基线 `e8cf480`：没有 `ConceptSchemeStore`，五个用例 `ImportError`。
- 若 `put` 不做覆盖，`test_file_store_upsert_replaces_same_scheme` 失败。
- 若文件后端不按 tenant 分目录，`test_file_store_isolates_tenants` 失败。

## 5 问威胁建模

1. **数据**：企业术语表（概念、标签、映射）。
2. **调用方**：编排路由、控制台（后续切片）。
3. **信任边界**：企业自定义语义声明 → 存储。
4. **恶意输入最坏结果**：租户 A 读到租户 B 的术语表（串租户）；路径注入读到目录外。缓解：租户隔离
   （文件按租户分目录、Postgres 按 tenant 过滤），路径走 `safe_join`。
5. **失败是否泄露信息**：存储错误只报类型，不泄 DSN 或术语内容。

## 范围外

- 数据领域维（SLICE-219）、能力映射（SLICE-220）、确定性路由（SLICE-221）。
- 术语表的删除与版本化（后续评估）。
- RLS 强制（MVP 应用层过滤，与 trigger store 一致）。

## 证据

- `docs/evidence/SLICE-218-terminology-storage.txt`
