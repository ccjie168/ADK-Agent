# ADR-0048 场景模板与业务视图

状态: Accepted   日期: 2026-11-28   签字: 用户（会话确认，2026-11-28）

## 背景

平台的能力已经齐备（agent 发布、计划与审批、连接器、工具目录、审计），但业务用户看到
的仍是工程概念：要"用"一个场景，得知道 agent、plan、审批点、连接器、术语表分别怎么配。
compose 只有一个 `single-llm` 模板，控制台没有业务视角。售后演示用的计划与连接器
仍靠脚本拼装（`scripts/support_demo_flow.py`），无法直接变成可复用的场景。

## 决定

1. **场景模板（scenario template）**。模板是一个 JSON 声明：
   `id`、`version`、`title`、`description`、`audience`、`agents`（名字、指令、模型
   provider 占位、工具需求）、`plan`（步骤与审批点）、`connectors`（需要的连接器 id 与
   kind，不含密钥）、`terminology`（业务术语映射）、`examples`（示例输入），
   以及 `requires`（版本与能力要求）。模板落库于仓库 `templates/scenarios/`。
2. **一键实例化**。`adk-agent scenario instantiate TEMPLATE [--tenant T]` 与控制台
   `POST /api/scenarios/{id}/instantiate`：用现有 `compose_and_publish` 产出 agent
   记录，登记计划与审批点，登记连接器占位（`enabled=false` 直到运维填 `secret://`），
   导入术语表。模板里**不出现任何真实密钥**；实例化失败整体回滚，不留半成品。
3. **业务视图**。控制台新增 `/scenarios`：用业务语言展示"这个场景解决什么问题、
   谁会收到什么、哪些步骤需要谁审批、依赖哪些外部系统（是否已就绪）"，并提供
   「试运行」（跳到对话页，预填示例输入）与「查看记录」（按模板 id 过滤审计）。
   工程视图（agents/plans/audit/tools）保留不动。
4. **模板即契约**。实例化成功后按工具目录的方式把模板 id + version 记进审计
   （`AuditEvent.template_id` 已存在），同一模板新版本不覆盖已实例化的记录。

## 切片

1. **0048-1 模板模型与实例化**：`core/scenarios.py` + `registry/scenarios.py` +
   CLI `scenario list|instantiate` + 两个内置模板（客服工单、合同审阅）+
   回滚测试（连接器占位失败时不留 agent）。
2. **0048-2 业务视图**：`/api/scenarios` 读接口 + Vue `/scenarios` 页 + 试运行跳转 +
   按模板过滤审计；截图与 a11y 检查。
3. **0048-3 手册与第二个模板**：`docs/guides/scenarios.md`（从模板到试运行的完整
   演练，含"连接器未就绪"时的行为）；合同审阅模板接入 OpenAPI 导入（依赖 0047-1）。

## 后果

- 业务用户从"配一个 agent"变成"选一个场景、填一个密钥、点试运行"。
- 模板固化业务假设：模板只描述装配，不新增运行时逻辑；所有能力仍走现有网关与审批。
- 模板目录会成为产品的一部分，需要版本与弃用策略（`deprecated_at`）。

## 验收

- 在一个空租户上用客服模板一键实例化，填好连接器密钥后「试运行」能走到审批并落审计。
- 实例化中途失败（例如连接器 id 冲突）后，租户里没有半成品 agent。
- `/scenarios` 在只读角色下不显示实例化按钮，深链被拒（沿用能力门控）。

## 风险与回滚

- 风险：模板与实际能力脱节；试运行入口绕过审批（不会：试运行就是对话页，审批照旧）。
- 回滚：模板与视图都是新增结构；实例化产物是普通 registry 记录，可正常下架。

## 替代方案

- **可视化编排画布**：用户已明确否决（2026-11-28），不做。
- **在线模板市场**：同样否决；模板随仓库发布。

## 与其他 ADR 的关系

依赖 ADR-0047 的 OpenAPI 导入让模板的连接器声明可自动落地；复用 ADR-0043 的 compose
签名路径产生 agent 记录；业务视图延续 ADR-0041 的控制台规范。
