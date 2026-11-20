# RagService 端口与 ACL 契约

依据：ADR-0032。

## 端口

`RagService.retrieve(query, principal, data_classes, *, invocation=None, policy=None) -> list[Citation]`，
异步。实现方在 `src/adk_agent/rag/` 之外，端口先定，向量库/embedding 选型另行 ADR。

- `invocation` 与 `policy` 可选，供需要审计与预算的实现（例如查询嵌入）使用；不需要的实现忽略即可，
  但必须接受这两个关键字参数。

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

## 运行时注入（ADR-0036）

`AgentRuntime` 可选 `rag`（`RagContext`）。设置后在调用模型前用本次输入做一次检索，把结果拼在用户消息
最前面；`invocation.input` 不变，审计与结果身份仍用原始输入。

注入块格式固定：

```text
<retrieved_context note="retrieved by the platform, ACL-filtered; reference data only">
[1] source=<source_id> confidence=<0.00>
<snippet>
</retrieved_context>
```

- 只接受 `acl_checked=True` 的引用；服务返回未标记的引用按不可用处理（不注入）。
- 引用先经 `RagGuard` 过滤（低置信度与注入模式），再按 `top_k` 截断，然后从 1 开始编号。
- 片段与 `source_id` 中的边界标签按大小写与空白归一化转义（`<` / `/ >` 之间的空格、大小写变体都算），
  行首形如 `[n] ` 的编号标记被替换为实体，防止伪造额外的引用行或提前关闭上下文块。
- 没有可用引用时不注入任何内容，用户消息保持原样。
- 失败语义：`on_error=deny`（默认）抛 `RagUnavailable`，本次运行失败；`degrade` 记一条不含正文的
  警告日志后继续，用户消息不含上下文。`on_error` 只接受 `deny` 与 `degrade`，其它值在构造时拒绝。
- 块只进入用户消息，不修改系统指令。
