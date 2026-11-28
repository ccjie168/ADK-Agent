# SLICE-320 OpenAPI 导入生成连接器（ADR-0047 切片 1）

状态: active
依据: ADR-0047 已确认（2026-11-28）

## 意图

`adk-agent connector import-openapi` 把一份 OpenAPI 文档变成受治理的连接器：
连接器记录带 `kind=openapi`、从文档推导的 `base_url`/`methods`/`path_prefixes`，
每个 `operationId` 成为一个工具（`<connector-id>.<operationId>`），写进连接器存储与
工具目录。网关按工具调用固定方法与路径，仍走现有 `_handler`，不新增执行路径。

## 契约（先改）

- `docs/contracts/connectors.md`（新）：`ConnectorSpec` 新增字段
  `operations: [{tool_id, path, method}]`（缺省空列表，additive）；导入规则、跳过规则、
  上限与错误码。
- 工具目录合并规则：相同 `tool_id` 且内容相同 = 幂等；内容不同 = 冲突，拒绝整次写入。

## 完成判据

- [ ] 文档生成连接器与逐操作工具 -> `test_import_builds_connector_and_operations`
- [ ] 缺 `operationId` 的接口被跳过并列出 -> `test_import_skips_operations_without_id`
- [ ] 非法文档给固定错误码 -> `test_import_rejects_bad_document`
- [ ] 工具数超上限给错误 -> `test_import_caps_tool_count`
- [ ] 生成的工具按固定方法与路径调用，路径参数被编码 -> `test_operation_tool_calls_fixed_path`
- [ ] 路径参数里的穿越尝试被拒 -> `test_operation_tool_rejects_traversal`
- [ ] 目录合并冲突拒绝 -> `test_catalog_merge_rejects_conflict`
- [ ] CLI 写入连接器与工具目录 -> `test_cli_import_openapi_writes_connector_and_catalog`
- [ ] `--full` 门禁通过

## 反例

实现前没有 `tools/openapi_import.py`、`ConnectorSpec.operations` 与逐操作工具，
七条用例 ImportError 或断言失败；CLI 没有 `import-openapi` 子命令。

## 5 问威胁建模

1. **数据**：文档来自运维本地文件；生成的工具继承租户与 `secret://` 引用，不含密钥。
2. **调用方**：CLI 与运维；网关按工具名分发。
3. **信任边界**：`base_url` 仍按 `ConnectorSpec` 的校验（https 或回环 http）；
   `path_prefixes` 从文档推导且不允许 `..`；路径参数 URL 编码后再过 `_path_allowed`。
4. **恶意输入**：文档里的 `servers[0].url` 可含凭据 → 直接拒绝（复用现有校验）；
   路径参数注入 `/` 或 `..` → 编码或拒绝。
5. **失败是否泄露信息**：错误只含错误码与接口名，不含密钥。

## 范围外

- MCP 连接器（0047-2）、插件入口（0047-3）。
- 从文档生成 agent 工具（现有 `AgentConfig.openapi` 不变）。

## 证据

- `docs/evidence/SLICE-320-openapi-import.txt`
