# SLICE-268 连接器与凭据表单（ConnectorsView / CredentialsView）

状态: draft
依据: 用户反馈「页面能力应在页面配置」；接口 `POST /api/connectors`、`POST /api/connectors/{id}/disable`、
`POST /api/credentials`、`POST /api/credentials/{id}/disable` 均已存在（`connectors.manage`）

## 意图

1. `ConnectorsView.vue`：`connectors.manage` 下显示「注册连接器」表单——`connector_id`、租户（留空为全局）、
   `kind`(http/openapi/mcp)、`base_url`、路径前缀（逗号分隔）、`auth_ref`（可选）、超时秒数、方法多选；
   `POST /api/connectors`。每行「禁用」→ `POST /api/connectors/{id}/disable`。
   错误码映射：`invalid_connector`、`connector_conflict`、`credential_unbound`，其余回退状态码。
2. `CredentialsView.vue`：`connectors.manage` 下显示「注册凭据引用」表单——`credential_id`、租户、
   `secret_ref`、描述；`POST /api/credentials`。每行「禁用」→ `POST /api/credentials/{id}/disable?tenant=`。
   页面只登记引用，密钥值仍由服务端环境变量提供，**不发送任何密文/明文密钥字段**。
3. 所有请求经 try/catch，网络失败显示「…失败: 网络错误」；结果消息在面板顶部。

后端无改动。

## 契约（先改）

无对外接口变化；四个端点已在 `docs/contracts/console.md` 记录。

## 完成判据

- [x] 连接器表单提交 `base_url`/`path_prefixes` 等字段并按 `connectors.manage` 显示 -> `test_connectors_view_registers_connector`
- [x] 连接器可禁用 -> `test_connectors_view_disables_connector`
- [x] 凭据表单提交 `credential_id`/`secret_ref` 并按 `connectors.manage` 显示 -> `test_credentials_view_registers_credential`
- [x] 凭据页面不发送任何密文字段 -> `test_credentials_view_never_sends_secret_material`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过
- [x] 实机验证：注册连接器、注册凭据各一次

## 反例

基线（SLICE-267 状态）：两个面板只读表格，无表单、无禁用按钮。上述用例失败（密文守卫用例在基线也通过，
因为只读视图同样不含该字段，目的是防止未来误加）。

## 5 问威胁建模

1. **数据**：连接器定义（URL/方法/路径前缀/凭据引用）与凭据**引用**；无密钥值。
2. **调用方**：浏览器；服务端按 `connectors.manage` 强制，注册连接器还校验 `auth_ref` 是否已绑定可用凭据。
3. **信任边界**：服务端 `ConnectorSpec`/`CredentialBinding` 校验（https-only 或 loopback、路径前缀无 `..`、
   `secret://` 形态）；审计 `connector.register`/`connector.disable`/`credential.register`。
4. **恶意输入**：前端只收集字段；服务端全量校验；渲染无 `v-html`。
5. **失败是否泄露信息**：固定文案或状态码。

## 范围外

- 凭据轮换（rewrap）、连接器健康检查按钮、连接器申请审批。
- 对端/远端目录、审批与工具授权决定按钮（下一批）。

## 证据

- `docs/evidence/SLICE-268-connector-forms.txt`
