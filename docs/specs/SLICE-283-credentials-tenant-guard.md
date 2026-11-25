# SLICE-283 凭据接口的调用方租户校验

状态: gated
依据: PROGRESS 第 16 条既有缺口（`/api/credentials` 对调用方自身非法租户返回 500）

## 意图

调用方租户来自 token/OIDC claim，可能不满足 `_SAFE_TENANT`。`GET /api/credentials` 与
`POST /api/credentials/{credential_id}/disable` 把 `tenant or caller.tenant` 直接交给存储：
文件存储的 `safe_join` 对非法租户抛 `ValueError`，不在 `CredentialStoreError` 的捕获范围内，
于是接口 500。显式 `?tenant=` 已做 400 校验，缺的只是调用方自身租户这一条路径。

修复：两个接口在解析出 `target` 后统一校验 `_SAFE_TENANT`，不合法返回 400 `unsafe_tenant`，
顺序为能力 → 存储配置 404 → 显式租户 403 → 安全租户 400 → 存储读写。合法租户与 admin
跨租户行为不变。

## 契约（先改）

- `docs/contracts/console.md` 的 `GET /api/credentials` 与 disable 两节：补充
  「`tenant` 缺失时用调用方租户；解析后的租户不合法返回 400 `unsafe_tenant`」。

## 完成判据

- [ ] 调用方非法租户列表返回 400 -> `test_credentials_list_rejects_an_unsafe_caller_tenant`
- [ ] 调用方非法租户停用返回 400 -> `test_credentials_disable_rejects_an_unsafe_caller_tenant`
- [ ] 显式非法租户仍是 400 -> `test_credentials_list_rejects_an_unsafe_explicit_tenant`
- [ ] 合法租户列表仍是 200 -> `test_credentials_list_keeps_a_safe_tenant`
- [ ] admin 跨租户列表不回归 -> `test_credentials_list_allows_admin_cross_tenant`

## 反例

实现前，前两条返回 500（`ValueError` 从 `safe_join` 逃逸）；显式非法租户与合法/跨租户用例
在旧代码上通过，作为回归保护（证据里注明）。

## 5 问威胁建模

1. **数据**：凭据**元数据**（id、租户、引用、描述、启用状态）；不含密文与明文。
2. **调用方**：读 `connectors.read`、写 `connectors.manage`；权限检查先于一切。
3. **信任边界**：租户字符串只用于拼路径；`_SAFE_TENANT` 与 `safe_join` 双重约束。
4. **恶意输入**：非法租户 400；显式跨租户 403；不存在 404；不回显存储异常文本。
5. **失败是否泄露信息**：固定错误码；日志只记租户与 id。

## 范围外

- 其他接口（连接器、对端等）的同类调用方租户校验，另行切片。
- Postgres 存储的错误映射。

## 证据

- `docs/evidence/SLICE-283-credentials-tenant-guard.txt`
