# ADR-0047 连接器导入、MCP 连接器与插件入口

状态: Accepted   日期: 2026-11-28   签字: 用户（会话确认，2026-11-28）

## 背景

连接器（`core/connectors.py`）已经有 `http`/`openapi`/`mcp` 三种 `kind`，但实际执行只有
一条路径：`tools/connectors.py` 里的 `_handler` 用 `HttpxAdapter` 按白名单的
路径前缀与 HTTP 方法发请求，`kind` 目前只出现在描述与展示里。

由此有三个具体缺口：

- **OpenAPI 导入只在 agent 配置里**：`AgentConfig.openapi` 指向本地文件，
  `tools/sources.py` 用 ADK 的 `OpenAPIToolset` 把它变成 agent 的工具；连接器目录、
  工具目录、风险分级、审批都拿不到这份声明。售后演示里两个连接器仍要手写登记。
- **MCP 只能"进"不能"当连接器用"**：`mcp/client.py` 让 agent 消费外部 MCP 服务器，
  但 MCP 服务器不能作为带租户、密钥引用、风险等级与审计的连接器登记。
- **没有插件机制**：新增一种外部协议或工具源必须改平台代码并发版，三方无法扩展。

## 决定

1. **OpenAPI 导入生成连接器**。新增
   `adk-agent connector import-openapi --spec FILE --connector-id ID [--tenant T]`：
   从文档的 `servers[0].url` 取 `base_url`，每个 `operationId` 生成一个工具 id
   （`<connector-id>.<operationId>`），路径与方法白名单取自文档，`data_classes`
   来自文档的 `x-data-classes` 扩展（缺省 `internal`），`risk_level` 缺省 L2；
   导入结果写入现有连接器存储与工具目录。网关侧仍走同一个 `_handler`，不新增执行路径。
   文档里没有 `operationId` 的接口跳过并在输出里列出。单次导入最多 200 个工具。
2. **MCP 连接器**。`kind="mcp"` 的连接器改由 `adapters.adk.mcp_tools` 建 MCP 客户端
   （`http` 用 `StreamableHTTPConnectionParams`，`stdio` 用 `StdioConnectionParams`），
   启动时 `list_tools`，把每个 MCP 工具按 `<connector-id>.<tool>` 名字注册进工具目录与
   网关；调用经同一套审批与审计。出站地址必须过 `check_url` 的 host 白名单；
   连接器的密钥仍只用 `secret://` 引用。MCP 工具名冲突时拒绝注册并记审计。
3. **插件入口**。定义 `adk_agent.plugins` entry point 组，`adk_agent.plugins_api`
   常量 =1。插件可提供：连接器适配器（新的 `kind` 执行方式）、工具源工厂、compose
   模板。加载在进程启动时进行：任一插件抛错只记一条审计并跳过，不阻断启动；
   `plugins_api` 不匹配时拒绝加载并记录原因。插件在进程内执行，不获得额外信任：
   它产出的工具默认 L3（需审批），只能用调用方声明的 `secret://` 引用。
4. **契约先行**。`docs/contracts/connectors.md`（新）与
   `docs/contracts/plugins.md`（新）先定字段；工具目录的 `source` 增加 `mcp`。

## 切片

1. **0047-1 OpenAPI 导入**：CLI、连接器契约、工具目录写入、测试（含无 `operationId`、
   超上限、非法文档三种反例）。
2. **0047-2 MCP 连接器**：适配层 MCP 客户端、启动探测、工具注册与前缀、审批与审计、
   出站白名单测试。
3. **0047-3 插件入口**：entry point 加载、`plugins_api` 校验、失败审计、插件契约与
   示例插件（只读 demo）、手册章节。

## 后果

- 售后演示的连接器可以直接从 OpenAPI 文档导入，不再手写登记脚本。
- MCP 服务器与 HTTP API 在连接器层面等价：同一套租户、密钥、审批、审计。
- 第三方可以在不改平台代码的前提下加协议；代价是插件是本进程代码，属于新增的
  安全风险面，必须按第 3 条的限制执行。

## 验收

- 用一份真实 OpenAPI 文档导入后，控制台连接器页与工具页可见，网关调用成功且有审计。
- MCP 连接器在回环 MCP 服务器上完成 `list_tools` 与一次走审批的调用。
- 一个故意抛错的插件不影响启动，审计里有 `plugin.load_failed`。

## 风险与回滚

- 风险：插件是进程内代码；MCP 客户端带来新的出站面。缓解：默认 L3、白名单、
  `secret://` 限定。
- 回滚：三类能力都挂在现有存储与网关后面，可逐切片回退；插件入口默认关闭
  （`--plugins` 显式开启）。

## 替代方案

- **继续手写连接器**：演示与接入成本高，不选。
- **只用 MCP 作为外部工具通道**：HTTP API 生态更大，且现有连接器已按 HTTP 治理，不选。

## 与其他 ADR 的关系

复用 ADR-0046 的适配层边界（MCP 客户端只在 `adapters/adk` 里碰 ADK）；连接器治理沿用
ADR-0011 的工具授权与 ADR-0022 的安全评审。
