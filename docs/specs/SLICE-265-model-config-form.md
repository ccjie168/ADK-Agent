# SLICE-265 模型默认值就近配置（ModelView 表单）

状态: gated
依据: 用户反馈「模型这类页面能力应在页面配置」；接口 `PUT /api/model-config` 已存在（`model.write`）

## 意图

ModelView 加「默认模型」表单：显示当前默认模型（`GET /api/model-config`），编辑后保存
（`PUT /api/model-config`）。写控件按 `model.write` 显示。

1. `onMounted` 时并行拉 `/api/model`（摘要）与 `/api/model-config`（默认模型）。
2. 表单：一个文本框 + 保存按钮；`canWrite = auth.hasCapability("model.write")`。
3. 保存结果：成功显示「已保存」并刷新；服务端 `[{error: invalid_model}]` 400 显示
   「模型名无效」；其他失败显示状态码。
4. 只读用户仍能看到当前默认模型，但没有保存按钮。

后端无改动。

## 契约（先改）

无对外接口变化；两个端点已记录在 `docs/contracts/console.md`（`GET/PUT /api/model-config`）。

## 完成判据

- [x] 视图读取 `/api/model-config` -> `test_model_view_reads_default_model`
- [x] 视图按 `model.write` 门控并 PUT `/api/model-config` -> `test_model_view_writes_default_model`
- [x] 前端可构建（`npm run build`）且 `--full` 门禁通过

## 反例

基线（SLICE-264 状态）：ModelView 只 GET `/api/model` 渲染摘要，无 `/api/model-config`、无写按钮。
上述用例在未改实现时失败。

## 5 问威胁建模

1. **数据**：默认模型名（如 `litellm:deepseek/deepseek-v4-pro`），非密钥。
2. **调用方**：浏览器；服务端按 `model.write` 强制（默认只有 admin）。
3. **信任边界**：服务端校验模型名格式（`is_valid_model_spec`）并写审计 `model.configure`。
4. **恶意输入**：前端只做非空校验；服务端仍全量校验。
5. **失败是否泄露信息**：只显示固定文案或状态码。

## 范围外

- 模型别名/候选策略编辑（`ModelPolicy` 位于 manifest，属发布期配置）。
- 连接器/策略/注册表等其余只读面板的写表单（后续切片）。

## 证据

- `docs/evidence/SLICE-265-model-config-form.txt`
