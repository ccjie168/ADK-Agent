# SLICE-266 策略页面编辑（PolicyView 保存）

状态: gated
依据: 用户反馈「页面能力应在页面配置」；接口 `PUT /api/policy` 已存在（`policy.write` + RBAC `policy.update`）

## 意图

PolicyView 从只读 JSON 变成可编辑：加载后在文本域中编辑策略 JSON，保存即 `PUT /api/policy`。
写控件按 `policy.write` 显示；只读用户仍能查看。

1. 挂载时 `GET /api/policy`，把 JSON 填进 `draft`（格式化 2 空格）。
2. `policy.write` 下显示文本域与「保存」；保存前本地 `JSON.parse`，非法 JSON 直接提示「JSON 格式无效」，
   不发请求。
3. 成功：用服务端返回的策略回填草稿并显示「已保存」；400 显示「策略无效」；403 显示「策略被拒绝」；
   其他失败显示状态码。
4. 只读用户仍看格式化 JSON。

后端无改动（服务端 `AccessPolicy` 校验 + `policy.update` RBAC + 审计均为既有实现）。
未配置 `--policy` 时路由不存在，面板显示 `policy unavailable`。

## 契约（先改）

无对外接口变化；`GET/PUT /api/policy` 已在 `docs/contracts/console.md` 记录。

## 完成判据

- [x] 视图 PUT `/api/policy` 且按 `policy.write` 门控 -> `test_policy_view_writes_policy`
- [x] 保存前本地 `JSON.parse` 校验 -> `test_policy_view_parses_json`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过

## 反例

基线（SLICE-265 状态）：PolicyView 只 GET `/api/policy` 并 `pre` 显示，无写按钮。上述用例失败。

## 5 问威胁建模

1. **数据**：RBAC 策略（租户/角色/allow/deny 模式），非密钥。
2. **调用方**：浏览器；服务端在 `policy.update` 上走 RBAC 决策并审计（ok/denied）。
3. **信任边界**：服务端权威；前端只做 JSON 语法预检。
4. **恶意输入**：服务端 `AccessPolicy.model_validate` 全量校验，非法返回 400。
5. **失败是否泄露信息**：只显示固定文案或状态码。

## 范围外

- 策略的可视化编辑（表格/规则生成器）。
- 注册表动作、连接器/凭据、对端、审批/授权决定（后续切片）。

## 证据

- `docs/evidence/SLICE-266-policy-save.txt`
