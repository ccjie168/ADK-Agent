# SLICE-157 文件凭据存储的读取与加锁健壮性

状态: gated
依据: PROGRESS 缺口清单第 8 条：Windows 文件锁对永久错误无限重试；旧超长凭据记录让控制台
`list` 抛未捕获的 `ValidationError`（500）。

## 意图

1. 文件存储统一用 `_read_binding` 解析记录；无法解析或不可读时抛 `CredentialStoreError`
   （固定文案，不回显路径或内容），读取路径 fail-closed。
2. Windows 文件锁通过 `_acquire_lock` 限次重试（默认 100 次、50 ms，约 5 秒），拿不到时抛
   `CredentialStoreError`，不再无限循环。
3. 控制台 `GET /api/credentials` 对这类记录返回 503 `credential_store_unavailable`；CLI 退出 1。
4. 契约先更新 `docs/contracts/credentials.md` 的存储段。

## 契约（先改）

- `docs/contracts/credentials.md`。

## 完成判据

- [x] 无法解析的记录让 `list` 抛存储错误 -> `test_store_reads_fail_closed_on_an_invalid_record`
- [x] 控制台列表对这类记录返回 503 -> `test_list_reports_an_invalid_record_as_unavailable`
- [x] 文件锁在有限次重试后放弃 -> `test_file_lock_gives_up_after_bounded_attempts`
- [x] 全量门禁通过

## 反例

- [x] 基线 `list` 对超长记录抛 `ValidationError`，控制台返回 500
- [x] 基线 Windows 锁分支是 `while True`

## 5 问威胁建模

1. **数据**：凭据绑定记录、锁文件。
2. **调用方**：控制台、CLI 与控制面读凭据存储的路径。
3. **信任边界**：磁盘上的旧记录到进程。
4. **恶意输入最坏结果**：无法解析的记录让读取崩溃（缓解：统一映射为存储错误，fail-closed）；
   锁被长期占用让进程卡死（缓解：限次重试后报错）。
5. **失败是否泄露信息**：固定错误文案，不含路径、记录内容或密钥。

## 范围外

- Postgres 存储的同类校验错误。
- 旧超长记录的迁移或删除（需要单独评审，当前 fail-closed）。
- 跨租户 admin 写入的审计归属。

## 证据

- `docs/evidence/SLICE-157-store-robustness.txt`
