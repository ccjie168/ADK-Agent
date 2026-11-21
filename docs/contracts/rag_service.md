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
- `confidence`（0..1）：截断到 `[0, 1]` 的余弦相似度（`max(0, 1 - distance)`）。`min_confidence`
  与它比较，默认 `0.5` 即余弦相似度门槛 `0.5`；正交（相似度 `0`）的引用置信度为 `0`，默认会被过滤。

## 摄取与替换

- 同一 `(tenant, source_id)` 的重新摄取是整源替换：写入新分块集合的同一事务里删除该来源不再存在的
  分块。文件变短不会留下陈旧尾部分块，其他来源不受影响。
- 切分后没有内容仍然拒绝摄取，已有分块保持不动。
- 替换以事务提交，读方看不到「已删除、尚未写入」的中间状态。

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
- 片段与 `source_id` 先做换行归一化（`\r\n`、`\r` 变 `\n`）并剔除 Unicode `Cf` 类格式控制字符
  （含 U+200B-U+200F、U+2060、U+FEFF 等），再把边界标签按大小写、空白与结尾 `/` 归一化中和；
  行首（含任意非换行前导空白）形如 `[n]` 的编号标记被替换为实体，防止伪造额外的引用行或提前关闭
  上下文块。
- 不在 `Cf` 类的不可见字符（例如 U+034F 组合字形连接符、U+FE0F 变体选择符、Hangul filler）不剔除，
  这是已知残余风险：它们不会破坏正文可读性，但插进标签词仍可能让模型读到近似闭合标记。需要更强保证
  时按 Unicode `Default_Ignorable_Code_Point` 另立切片。
- 没有可用引用时不注入任何内容，用户消息保持原样。
- 失败语义：`on_error=deny`（默认）抛 `RagUnavailable`，本次运行失败；`degrade` 记一条不含正文的
  警告日志后继续，用户消息不含上下文。`on_error` 只接受 `deny` 与 `degrade`，其它值在构造时拒绝。
- 块只进入用户消息，不修改系统指令。

## 检索审计（ADR-0036）

`RagContext` 配置了 `audit` 时，每次预取写一条 `rag.retrieve` 事件：

- 字段：`run_id`、`trace_id`、`tenant`、`principal`、`agent_ref`、`target=<agent id>@<version>`、
  `action="rag.retrieve"`、`status`、`error_code`、`latency_ms`、`data_classes`，以及 `rag_top_k`、
  `rag_returned`、`rag_filtered`。
- `rag_returned` 是实际注入的引用条数，`rag_top_k` 是本次生效的上限；`rag_filtered =
  服务返回条数 - 注入条数`，包含 ACL 未标记丢弃、`RagGuard` 丢弃与超过 `top_k` 的截断。
- 三个字段只在检索事件上序列化；未使用（`None`）时不写入事件的 JSON 载荷，因此新增字段不会改变
  既有事件的 canonical JSON 与链哈希，升级后可继续验证历史链。
- 审计写入失败让本次预取失败（fail-closed），不静默丢弃审计。
- 失败：`deny` 先写 `status=error`（`error_code` 为底层异常类型）再抛 `RagUnavailable`；`degrade`
  写同一条 `status=error` 后继续运行。
- 事件不含查询原文、片段与 `source_id`；`error_code` 只写异常类型名。
- 未配置 `audit` 时不写事件，运行行为与切片 2 一致。

## 入口接线（ADR-0036 切片 4）

`RagFactory` 持有一份共享的 `PgVectorRagStore` 与 `EmbeddingGateway`，`context(manifest)` 在
`manifest.rag` 存在且 `enabled=true` 时返回绑定了该 manifest 的 `RagContext`（`top_k`、
`min_confidence`、`data_classes`、`on_error`，策略取 `manifest.model_policy`），否则返回 `None`。

- `console` 只在按需加载（`/api/registry/load`，有 manifest）时接线；用 `--agents` 加载的 agent
  没有 manifest，不能开启检索。
- `serve-triggers` 在每次执行时用 pinned 记录的 manifest 构造上下文。
- 部署配置：`--rag-db`、`--rag-dimensions`、`--rag-model`、`--rag-provider`（默认 `litellm`）。
  未给 `--rag-db` 时完全不启用；给了但缺维度或模型退出 1；未知 provider 退出 1。
- 同一进程内所有 agent 共享存储与嵌入网关，嵌入预算与审计在该网关内累计。
- `RagFactory` 可传入部署级 `policy` 覆盖 manifest 的 `model_policy`；当前 CLI 不传，生产按 manifest 生效。
