# SLICE-158 控制台凭据列表的非法租户参数

状态: gated
依据: PROGRESS 缺口清单第 8 条：`GET /api/credentials?tenant=<非法值>` 由 `safe_join` 抛
`UnsafePath`，控制台返回 500。

## 意图

1. `GET /api/credentials` 在跨租户检查之后、能力检查之前校验 `tenant` 的安全字符集
   （`^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$`），不合法返回 400 `unsafe_tenant`。
2. 顺序与注册表列表一致：401/404 配置检查 → 跨租户 403 → 非法租户 400 → 能力 403 → 存储。
3. 契约先更新 `docs/contracts/console.md`。

## 契约（先改）

- `docs/contracts/console.md` 的 `GET /api/credentials`。

## 完成判据

- [x] 非法 `tenant` 返回 400 `unsafe_tenant` -> `test_list_rejects_an_unsafe_tenant`
- [x] 既有列表、能力与非法记录用例保持通过
- [x] 全量门禁通过

## 反例

- [x] 基线把 `bad/name` 传给 `safe_join`，抛 `UnsafePath`（500）

## 5 问威胁建模

1. **数据**：租户名、凭据绑定记录。
2. **调用方**：持有 `connectors.read` 的控制台用户。
3. **信任边界**：查询参数到文件路径。
4. **恶意输入最坏结果**：路径穿越或崩溃（缓解：字符集白名单，先于路径拼接）。
5. **失败是否泄露信息**：固定 400 `unsafe_tenant`，不回显输入。

## 范围外

- 凭据读写接口里 `credential_id` 路径参数的同类校验（disable 已有 `_SAFE_NAME` 检查）。
- 其他接口的租户参数审计。

## 证据

- `docs/evidence/SLICE-158-credentials-tenant-query.txt`
