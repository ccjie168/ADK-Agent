# 复盘：从切片堆叠到可验证的产品（2026-11-21）

基线 `38841ea`，203 个切片、PR #22–#162、37 份 ADR、1890 个通过用例。本文回答两个问题：
已经建成了什么，以及哪些结论有真实运行的证据。

## 一、规模与结构

平台按契约分层：`core` 定义类型与端口（manifest、审计事件、调用、授权、配额），
`models` / `tools` / `audit` / `secretstore` / `registry` / `rag` 是适配器，
`runtime` 与 `orchestration` 负责执行，`console`、`mcp`、`a2a`、`triggers` 是入口，
`sandbox` 是隔离边界。对外有 HTTP 服务、CLI 与一套契约 schema。

治理主线已经闭环：角色与能力（ADR-0028/0030）、风险分级（ADR-0029）、工具授权与审批、
写工具幂等（ADR-0034）、模型别名与预算（ADR-0033）、RAG 端口与运行时接入（ADR-0032/0035/0036）、
审计链按存储内容校验（ADR-0037）。多副本所需的状态（配额、审批、审计、注册表、会话）
都有 Postgres 实现，文件后端作为开发与单机部署的默认。

## 二、这次“prove it works”证明了什么

新增 `scripts/prove_it_works.py`：12 项检查，每项都起真实进程或真实容器、走真实协议、
查真实落库结果；模型与嵌入是本地 OpenAI 兼容桩，其余全是真的。完整结果见
`docs/evidence/prove-2026-11-21.txt`，要点：

- 审计链在文件与 Postgres 两种后端都能验证，并且篡改一行就断链（P2）。
- 签名工件可经 HTTP 发布、按引用加载、真实对话并留下 `agent.run` 审计（P3）。
- 工具网关按 manifest 授权，需审批工具被拒并审计，写工具缺幂等键被拒、重放只执行一次（P4）。
- MCP 与 A2A 的认证边界都挡住了匿名调用；A2A peer 在授权前后行为不同（P5、P6）。
- pgvector 真实建表、真实嵌入（桩）、ACL 生效、检索上下文进入提示、`rag.retrieve` 不含原文（P7）。
- 模型网关按注册表策略拒绝非白名单 provider（P8）。
- 审批在两个进程间共享，并发决定只有一个赢家（P9）。
- Webhook 触发按幂等键去重，带审批授权的 agent 被直接拒绝（P10）。
- 配额计数在两个 console 进程间共享（P11）。
- 备份恢复后审计链仍可验证（P12）。

这十二项覆盖的是“能不能跑通、边界是否真的挡得住”，不覆盖性能、UI 体验与外部供应商质量。

## 三、质量信号

- 门禁：`--full` 9 步全 PASS，1890 passed / 98 skipped；skip 集中在无 `TEST_POSTGRES_URL`、
  无 `a2a-sdk`、POSIX-only 与符号链接。
- 每个切片都有 spec、负向证据与独立只读验证；验证代理多次拦下过度声明（RAG 手册、审计链历史记录、
  测试断言过弱），说明“实现者自述”不可作为合并依据的规则在起作用。
- 仍然发生过真实过程事故：SLICE-199 在 `master` 上提交后才发现没建分支（远端未被污染），
  之后把“提交前检查分支”写进了交接记忆。

## 四、本轮暴露的问题

1. **console 启动引用的 agent 不会检索**（真实缺口）。`console.py` 启动循环
   `for name, agent in list(agents.items()): _register(name, agent)` 不传 manifest，
   而 `_register` 只在 `manifest is not None` 时构造 `RagContext`。按需加载路径正常。
   后果：用 `--agent-ref` 起的生产控制台，检索静默失效且没有 `rag.retrieve` 审计。
2. **直连模型请求不受 `model_allowlist` 约束**。`PolicyModelGateway.complete` 的直连分支只检查
   `provider_allowlist`；`model_allowlist` 只在别名路由里过滤候选。需要确认这是否是预期语义；
   如果不是，这是一条策略绕过面。
3. **`triggers register --digest` 要求 `sha256:` 前缀**，注册表记录却是裸 hex；服务端会归一化，
   功能可用，但命令行人容易踩。
4. **无 OIDC 的 console 固定租户 `local`**，RAG 只能看到该租户文档。本地演示没问题，正式部署
   必须由 OIDC claim 提供租户，运维手册应写明这一点。
5. **`[litellm]` extra 的未锁定解析会引入带漏洞的 `wcmatch`**，开发 venv 装完 extra 后 `--full`
   的 `deps` 步会红。镜像与 CI 用 `requirements/runtime.lock` 没这个问题；验收机应在跑完
   `prove_it_works.py` 后恢复依赖，或先按 lock 安装。

## 五、仍然不能证明的部分

- 沙箱：POSIX-only，Windows 本机跑不了；平台门槛（降 uid、网络命名空间）也未在 Linux 上验收。
- 多副本：`deploy/k8s` 只有清单和文本守卫，没有集群部署与滚动升级演练。
- 外部模型与嵌入：本轮是桩；真实 Gemini/Claude/DeepSeek 的配额、限速、成本与 embedding 质量未验。
- OIDC 与浏览器 UI：没有真实 IdP 与自动化点击。
- Redis 跨副本限流、压测、长时间 soak 未在本轮重跑。

## 六、教训

- 文档比代码更容易说过头。三轮验证里最反复的发现都是“手册承诺了代码没做的事”。
  以后凡是写“会自动”“会恢复”“只可能”的句子，都要能指到一条真实运行证据。
- 单元测试多不等于系统可运行。1890 个用例没有发现“启动引用不检索”，因为每个用例只验证自己那层。
  这次把验证放在进程边界上才看见它。
- 环境差异是真实风险：Windows 跳过沙箱、容器镜像缺 pgvector、Docker Hub 不可达需要镜像源。
  对外承诺必须按“部署环境”而不是“开发机”来写。

## 七、建议的下一步（按风险排序）

1. 修 console 启动引用的 RAG 接线，补一条“启动引用也检索”的负向用例，并让 `prove_it_works.py`
   的 P7 改成启动引用路径（现在测的是按需加载）。
2. 确认 `model_allowlist` 的预期语义；若应约束直连请求，按 ADR 改网关并补反例。
3. 接线 MCP/A2A 的 RAG，以及沙箱化触发的检索缺口（已知项，PROGRESS 第 9 条）。
4. 给 `prove_it_works.py` 加一个 `--smoke` 子集（P1–P4）作为发布前检查；完整 12 项留给验收环境。
5. 在 Linux CI 或一台 Linux 机器上跑一次沙箱与多副本清单的真实部署演练。
6. 申请一次真实供应商的验收窗口，验证模型/嵌入通道与预算累计。
