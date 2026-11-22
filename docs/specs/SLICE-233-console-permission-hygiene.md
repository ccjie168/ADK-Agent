# SLICE-233 控制台路由权限一致性

状态: gated
依据: ADR-0022（能力驱动角色视图）+ ADR-0030（生产角色分离）收尾；用户 2026-11-22 确认「权限收紧」方向。

## 意图

把控制台每一条带能力/授权检查的路由对齐到两条硬规则：

1. **检查在前**：能力/授权检查必须是 `_principal_for(request)` 之后的第一条语句，先于
   `*-_not_configured` 404、非法参数 400、租户判断与 store 读取。关闭「未授权调用方用 404/400 探测
   配置是否存在」的侧信道（SLICE-132 已对审批三路由这样做，本切片推广到全部）。
2. **写路径能力化**：写路由的 `if "admin" not in caller.roles` 换成 `_forbidden_if_missing(caller,
   "<manage>")`，与前端 `data-capability` 一致，去掉「角色字符串判断」与「能力清单」两套并存机制。

## 契约（先改）

- `docs/contracts/console.md`：为每条写路由补一句「需要 `<capability>` 能力，缺少返回 403
  `forbidden`」；说明能力检查先于「未配置 404」与「非法参数 400」。

## 完成判据

- [x] 读路由能力检查先于 config-404 -> `test_unconfigured_read_routes_403_before_404`
- [x] 写路由能力检查先于 config-404 -> `test_unconfigured_write_routes_403_before_404`
- [x] 写路径能力化（admin 判定换 `connectors.manage`/`peers.manage`）由既有写能力用例覆盖，无独立新用例
- [x] 全量门禁通过

## 反例

- 基线 `10d44c1`：以缺能力的 `requester` 调用未配置的读/写路由（`/api/credentials`、
  `/api/connector-requests`、`/api/peers`、`/api/remote-agents`、`/api/connectors/{id}/check`、
  `/api/peers/{id}/disable`、`/api/peers/{id}/grants`、`/api/remote-agents/{id}/refresh`）返回
  404/400（配置存在性泄漏），改为能力检查在前后应返回 403。写路径能力化本身无行为差异（admin 判定与
  admin-only 能力等价），故该条为「一致性替换」，无独立红态，在本节如实说明。

## 5 问威胁建模

1. **数据**：配置存在性（是否装了 connectors/credentials/peers/remote-agents 后端）。
2. **调用方**：控制台浏览器（Bearer token 鉴权后）。
3. **信任边界**：`connectors.manage`/`peers.manage` 是 admin-only 能力，替换后语义不变。
4. **恶意输入最坏结果**：目前未授权调用方可枚举配置存在性；改后统一 403，无信息。
5. **失败是否泄露信息**：403 固定 `{"error": "forbidden"}`，不泄露任何状态。

## 范围外（需你另行拍板，本切片不碰）

- `POST /api/import/terminology` 与 `POST /api/import/agent` 目前无能力检查（基础角色也能写术语表/
  发布 agent）。是否收紧为 `registry.publish`（agent）与新的语义写能力（terminology）属设计决策。
- 只读面板（quota/rag/model/semantics/overview）当前是 `runs.read`（基础，人人可见）。是否改为
  operator 可见属「不能所有都可见」的实质取舍，需单独定。

## 证据

- `docs/evidence/SLICE-233-console-permission-hygiene.txt`
