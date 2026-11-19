# FR 验收矩阵（草稿）

状态：草稿，待评审确认。
依据：目标文档 FR-001 到 FR-016（`docs/specs/ADK_Agent_Product_Architecture_Specification_v1.0.docx`）与现有代码（`master` @ `7cf1398`）。

## 列说明

- 支持度：GREEN 已达标 / AMBER 部分达标 / RED 缺失或不可用，是评审推断。
- 测试用例名是草拟，写进 spec 后必须由 `scripts/check_specs.py` 校验真实存在，再落到 `tests/`。

| FR | 优先级 | 支持度 | 正例验收用例 | 反例验收用例 | 草拟测试用例名 | 现状缺口 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-001 身份与会话 | Must | GREEN | OIDC 登录后 tenant/roles/attributes 绑定到 session | 无 token 或无 tenant 的主体被拒 | `test_oidc_session_binding` | `auth.py`、`identity/`、`runtime/sessions.py` 已具备 |
| FR-002 多渠道 | Must | RED | Teams 消息路由到与 Web 同一任务 | 跨渠道任务状态不一致 | `test_teams_channel_task` | 仅 Web 控制台，无 channel adapter |
| FR-003 任务规划 Planner | Must | RED | 请求产出结构化步骤 + 成功条件 + 风险等级 | 计划 schema 非法被拒 | `test_planner_plan_schema` | `PlanExecutor` 有 supervisor 无 planner |
| FR-004 专家执行 Specialist | Must | AMBER | 步骤只在授权工具集内执行 | 越权工具调用被拒 | `test_step_tool_grant_enforced` | `PlanStep` + `tool_grants` 已有，缺角色化协议 |
| FR-005 结果复核 Reviewer | Must | RED | 复核输出通过/退回/升级 + 问题清单 | 无来源结论被退回 | `test_reviewer_reject_no_citation` | 无 reviewer 角色或复核步骤类型 |
| FR-006 工具调用与目录 | Must | AMBER | 目录含 schema/版本/Owner/超时/幂等 | 缺幂等键的写工具被拒 | `test_tool_catalog_metadata`、`test_tool_idempotency` | `ToolEntry` 字段不足（`tools/catalog.py`） |
| FR-007 人工审批 HITL | Must | GREEN | 高风险写操作审批前不执行 | 审批超时/拒绝后不执行 | `test_approval_before_write` | `approvals.py` 已具备，缺影响预览 |
| FR-008 知识检索 RAG | Must | RED | 答案带可访问来源引用 | 越权文档不可检索 | `test_rag_acl_filter`、`test_rag_citation` | RAG 整体缺失 |
| FR-009 记忆管理 | Should | RED | 短期/偏好/业务长期分层读写删除 | 跨会话或跨用户串扰 | `test_memory_layer_isolation` | 仅 ADK session，无分层记忆 |
| FR-010 模型路由 | Must | RED | 主模型故障降级且权限不变 | 受限数据进未批准端点被拒 | `test_model_fallback`、`test_data_class_provider` | 无 alias/路由/降级/预算执行 |
| FR-011 中断与恢复 | Must | AMBER | 长流程暂停/恢复/取消/幂等重试 | 重复写不产生重复业务记录 | `test_plan_resume`、`test_idempotent_retry` | 有 checkpoint 与触发幂等，缺任务面与通用写幂等 |
| FR-012 通知 | Should | RED | 审批/失败/完成经 Teams/邮件通知 | 通知失败不影响主流程 | `test_notification_outbox` | 仅审批回调（`approvals.py:372`） |
| FR-013 运营控制 | Must | AMBER | Ops Console 查看任务/trace/成本/失败并停用 | 停用在途运行被取消 | `test_ops_console`、`test_kill_switch` | console 有面板，无全局 kill switch |
| FR-014 配置与版本 | Must | AMBER | Agent/Prompt/Model/Tool/Policy 版本化关联发布 | 未签名或发布不匹配被拒 | `test_publish_verification` | agent 有版本，prompt/tool/policy 无统一版本模型 |
| FR-015 反馈与评估 | Must | AMBER | 用户反馈落库并进入评估闭环 | 无关联任务的反馈被拒 | `test_feedback_loop` | 有离线 `eval.py`，无用户反馈 |
| FR-016 多语言 | Should | RED | 中英输入输出，业务术语与系统字段映射 | 时区/数字按用户区域呈现 | `test_i18n_locale` | 无 i18n 实现 |

## 关联 NFR 验收（缺口项）

| NFR | 支持度 | 验收判据 | 证据缺口 |
| --- | --- | --- | --- |
| NFR-001 99.9% 可用性 | AMBER | 无单点、故障自愈 | 无 HPA/NetworkPolicy，需压测与演练 |
| NFR-002 P95 延迟 | GREY | 知识 15s/工具 30s/工作流 90s | 无生产遥测与 P95 基线 |
| NFR-004 100→1000 并发 | GREY | 压测报告 | `scripts/loadtest.py` 存在，仓库无结果 |
| NFR-006 RTO 4h/RPO 15m | AMBER | DR 演练达标 | 有 `backup.py`，无复制方案与演练 |
| NFR-009 覆盖率 ≥80% | RED | 覆盖率门禁 | `check.py` 无 coverage 阈值 |
| NFR-011 成本预算 | AMBER | 超基线 2 倍告警 | 成本可观测，无预算执行与告警 |

> 说明：NFR-001/002/004/006 的验收需要压测与演练，不是代码切片能单独完成；NFR-009 需在 `check.py` 加 coverage 门禁；NFR-011 需成本告警规则。
