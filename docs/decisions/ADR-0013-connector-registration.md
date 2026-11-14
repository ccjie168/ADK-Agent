# ADR-0013 连接器与外部 API 工具注册

状态: Proposed   日期: 2026-11-14   签字: 待签

## 背景

工具目前有三种形态：进程内函数工具、OpenAPI 导入的 toolset、MCP 工具。工具目录（SLICE-075）是一份静态 JSON，描述工具 id、来源与数据分级；授权走 manifest 与临时授权（ADR-0011）。

缺的是“外部 API 连接器”的注册与治理：谁有权注册一个外部端点、凭据放在哪、出站范围如何限制、调用如何审计。现状里 `openapi_toolset_from_config` 直接把 URL 写进配置，凭据没有统一入口，出站也没有白名单。

要求 4 明确要 API、MCP、function 与 connector 四类访问机制，并有授权与监管。这是方向评审 Phase C 的后半段。

## 决定

1. **连接器是独立注册对象。** 新增 `ConnectorSpec`：

   ```text
   connector_id: safe name
   tenant: safe name | null（null = 全局）
   kind: "http" | "openapi" | "mcp"
   base_url: https://...（http 只允许回环地址）
   auth_ref: "secret://..." | null
   methods: ["GET", "POST", ...]
   path_prefixes: ["/v1/crm/", ...]
   data_classes: [...]
   timeout_seconds: 1..60
   max_response_bytes: 1..8 MiB
   ```

   存在控制面 Postgres 表 `adk_connectors` 与文件实现（单机开发）。注册、查看与停用走控制面接口，只有 admin 能写。

2. **凭据只存引用。** `auth_ref` 一律是 `secret://` 引用，由现有 `SecretProvider` 在调用时解析；连接器记录、工具目录与 manifest 都不含明文。启动时解析失败则该连接器不可用，调用返回明确错误，不静默降级为匿名。

3. **出站策略在调用点强制。** 只有 `methods` 与 `path_prefixes` 覆盖的请求可以发出；`base_url` 的 scheme/host 固定，禁止重定向到其他 host；超时与响应大小按连接器配置截断。越界请求拒绝并写 `tool.call` 审计，`egress="third_party"`、`error_code="egress_denied"`。

4. **连接器工具进入同一授权体系。** 每个连接器可以暴露一个或多个工具 id（例如 `crm.read`）。这些工具进工具目录，agent 仍需 manifest 授权或 ADR-0011 的临时授权；连接器注册本身不授予任何 agent 访问权。

5. **控制台与 CLI。** 控制台新增只读连接器列表与注册表单（admin）；CLI `adk-agent connectors list|register|disable`。注册与停用写审计（`connector.register`、`connector.disable`）。

6. **v1 不做 OAuth 授权码/刷新令牌、不做响应转换 DSL、不做按连接器的独立限流。** OAuth 需要的令牌存储与回调属于后续 ADR；出站限流沿用入口与运行时现有机制。

## 备选与否决

- **继续把 URL 与凭据写进配置文件**：无法审计、无法按租户隔离、轮换要改文件；否决。
- **连接器注册即授权给所有 agent**：违反最小权限；否决，仍走 grant。
- **在网关层统一代理所有出站**：更彻底，但需要新服务与网络改造；v1 在调用点做策略，后续可把连接器执行搬进独立网关。
- **凭据加密存进连接器表**：引入密钥管理与解密路径；已有 `SecretProvider` 抽象，先复用引用。

## 后果

- 外部 API 有了注册、凭据引用、出站白名单与审计，工具目录能显示连接器来源。
- 多一层配置与控制面表；注册错误的连接器会在首次调用时暴露，而不是启动时（可选加健康检查）。
- 出站策略在进程内强制执行，不是网络隔离。
- 后续切片：类型与存储、控制面接口、执行适配器（HTTP/OpenAPI/MCP）、控制台与命令。

## 待签确认

请确认三点，确认后状态改为 Accepted：

1. 连接器是独立注册对象（`ConnectorSpec`），存 Postgres（文件实现用于开发），只有 admin 能写，按租户或全局可见。
2. 凭据只存 `secret://` 引用，由 `SecretProvider` 解析；解析失败时该连接器不可用，不降级为匿名。
3. 出站按 methods、path_prefixes、固定 host、超时与响应大小强制，越界拒绝并写 `egress=third_party` 审计；v1 不做 OAuth。
