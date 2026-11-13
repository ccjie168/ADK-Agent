# ADR-0008 Agent 工件与可插拔加载

状态: Accepted   日期: 2026-11-13   签字: Jie CAO（会话确认）

## 背景

方向评审（`docs/reviews/architecture-direction-20261113.md`）确认：平台注册的是 manifest 和评测报告，运行时从本地 `agent.py` 加载。注册、市场、版本固定和按 digest 运行都缺少"可运行工件"这一层。已确认的方向是：工件格式保持可插拔，注册表先 Postgres，市场只对内，A2A 先内部 peer。

不决定的后果：市场只能列出元数据，无法安装和运行；发布者签名无从谈起；注册表里的版本和实际运行的代码可以对不上。

## 决定

1. **工件是确定性 zip 归档。** 一个 agent 工件包含 `manifest.json`、入口模块（默认 `agent.py`）、可选的 `requirements.txt` 和 `README.md`。归档必须字节级确定：条目按名字排序、时间戳固定为 1980-01-01、文件权限固定 0644（目录 0755）、压缩参数固定。工件标识是归档字节的 `sha256`，写作 `sha256:<hex>`。

2. **工件元数据是加法，不改已有字段的语义。** 新增 `AgentArtifact`：`digest`、`media_type`（第一版只允许 `application/vnd.adk.agent+zip`）、`size`、`entrypoint`、`signature`、`key_id`。`PublishedAgent` 增加可选 `artifact: AgentArtifact | None`；`AgentRef` 增加可选 `artifact_digest: str | None`。现有 `PublishedAgent.digest` 仍是 manifest 摘要，现有发布的兼容性不变；按工件运行时以 `artifact_digest` 为准。

3. **两个端口。** `ArtifactStore`（`put`、`get`、`has`，按 digest 存取字节）和 `ArtifactLoader`（`load(artifact, store) -> BaseAgent`）。装配在 composition root。第一版适配器：
   - `PostgresArtifactStore`：`adk_artifacts(digest, media_type, size, bytes)`，单工件上限 8 MiB，超出拒绝发布。
   - `FileArtifactStore`：`<root>/sha256/<hex>/` 内容寻址目录，只用于演示和测试。
   - `InProcessArtifactLoader`：解包到临时目录，做路径穿越与大小检查，用 `importlib` 加载入口模块，要求模块暴露 `agent` 或 `root_agent`，且 `agent.name` 等于 manifest 的 `id`。

4. **签名是发布信任的边界。** 发布者用 Ed25519 私钥对工件 digest 签名，公钥进部署内的可信密钥表（环境变量或配置文件，按 `key_id` 索引）。加载器在导入代码之前验签：没有签名、`key_id` 不认识或验签失败一律拒绝。签名依赖 `cryptography`，写成可选 extra `publish = ["cryptography>=42"]`；缺依赖时发布工件失败并给出安装提示，manifest-only 发布不受影响。

5. **发布工件是可选动作。** `adk-agent publish PATH --artifact DIR|ZIP [--key FILE]` 在原有发布之上附加工件；不带 `--artifact` 时行为不变。带工件发布要求签名，签名失败不写注册表。工件元数据随版本写入 Postgres，字节进 `ArtifactStore`。

6. **运行时按引用加载。** 新增装配函数 `load_agent(registry, ref, store, loader)`：按 `AgentRef` 取版本元数据，用 `artifact_digest` 从 store 取字节，验签后交给 loader。控制台和 MCP 的现有 `--agent`/`--agents` 本地文件路径保留为开发模式；从注册表启动的开关在后续切片加，不在这里改行为。

7. **依赖只声明不安装。** `requirements.txt` 是元数据，加载器不执行 pip。缺依赖时加载失败并报出缺失模块名。自动解析与安装依赖需要单独的 ADR，涉及供应链与网络隔离。

8. **注册表元数据先落 Postgres。** 新增 `PostgresAgentRegistry` 实现现有 `AgentRegistry` 端口，表和索引随实现切片给出；`FileAgentRegistry` 降级为演示实现。控制面 HTTP API 不在此 ADR，见后续 ADR-0009。

9. **市场限定租户内。** 工件与目录按租户隔离，可信密钥表按部署配置，不做跨租户发布或跨组织信任。

10. **加载器的可插拔边界。** 后续的容器加载器、远端加载器实现同一个 `ArtifactLoader` 端口，不改变注册表、发布命令和审计数据结构。工件形态的差异只体现在 `media_type` 和对应的加载器上。

## 备选与否决

- **只支持容器镜像**：部署重、冷启动慢，本地开发和测试成本高；作为后续加载器保留。
- **源码目录直接入库**：没有确定性摘要，版本可漂移；否决。
- **把依赖打包进工件**：工件体积失控，供应链审查复杂；第一版不打包。
- **工件只放共享卷**：违反 ADR-0002 第 8 条"本地盘不存状态"；作为 `FileArtifactStore` 的演示用途保留。
- **沿用 `PublishedAgent.signature` 做工件签名**：该字段是 manifest 的完整性标记，改变语义会破坏既有断言；新增 `AgentArtifact.signature`。

## 后果

- 发布与运行之间第一次有了可核对的代码身份；市场、回滚和"按 digest 运行"有了前提。
- 加载器执行的是已发布代码，这是明确的信任边界。签名和可信密钥表是载荷，不能只靠审计兜底。进程内 loader 不是沙箱；不可信发布者需要容器或独立 worker，留给后续切片。
- 工件上限 8 MiB 和 zip 安全检查（拒绝绝对路径、`..`、符号链接、超限解压）必须由实现切片覆盖反例测试。
- `publish` 不带工件时保持兼容；带工件时新增签名依赖，默认安装不变。
- ADR-0002 第 3 条"发布时签名"在这里首次真正落地，落到工件而不是 manifest。
- 后续切片顺序：契约与类型、`ArtifactStore` 两个实现、发布带工件与签名、`InProcessArtifactLoader` 与验签、`load_agent` 接线、Postgres 注册表、控制面 API（ADR-0009）。

## 确认记录

2026-11-13 会话确认，三点均按本 ADR 采纳：

1. 工件用确定性 zip，标识为归档 sha256。
2. 工件字节先存 Postgres（单件 8 MiB），不引入对象存储。
3. 签名用 Ed25519，新增可选 extra `publish = ["cryptography>=42"]`。
