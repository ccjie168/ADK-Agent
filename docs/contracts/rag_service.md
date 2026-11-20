# RagService 端口与 ACL 契约

依据：ADR-0032。

## 端口

`RagService.retrieve(query, principal, data_classes) -> list[Citation]`，异步。实现方在
`src/adk_agent/rag/` 之外，端口先定，向量库/embedding 选型另行 ADR。

`Citation`：

- `source_id`（非空）：来源标识。
- `snippet`（非空）：检索片段。
- `acl_checked`（bool）：`True` 表示已按调用方权限过滤。
- `confidence`（0..1）：置信度。

## ACL 契约

- 检索必须按调用方权限过滤，绝不返回调用方无权访问的来源。
- `acl_checked=True` 是「已按 `principal` 权限过滤」的标记；检索结果交给调用方前必须置真。
- ACL 元数据在摄取时绑定到来源，检索时按 `principal` 判定。
- 同步延迟作为契约字段（权威源 + 容忍值），默认 SharePoint 为权威，容忍值待 Owner 确认。

## manifest 配置（ADR-0036）

`AgentManifest.rag` 可选，缺省 `None` 表示运行路径不做检索。

| 字段 | 类型 | 缺省 | 约束 |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | 打开后运行路径在调模型前做一次检索 |
| `top_k` | int | `5` | 1..50 |
| `min_confidence` | float | `0.5` | 0..1，传给 `RagGuard` |
| `data_classes` | list[DataClass] | `[]` | 四个枚举值；空列表只命中未分级分块 |
| `on_error` | `deny` \| `degrade` | `deny` | `degrade` 是显式的安全风险接受 |

- `rag` 为 `None` 时不进入 digest 载荷，存量记录的 digest 不变；显式给出（包括 `enabled=false`）参与
  digest，改动配置等于换一个发布摘要。
- `enabled=true` 时预取只用本次输入，不追溯多轮历史。
- `on_error=deny` 时检索不可用让本次运行失败；`degrade` 记审计后无上下文继续。
