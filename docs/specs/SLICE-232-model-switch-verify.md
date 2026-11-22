# SLICE-232 验收：改配置后新 chat 用新模型

状态: gated
依据: ADR-0040 MVP 第 3 项（prove_it_works 断言 + pytest 覆盖优先级与权限）

## 意图

1. `scripts/prove_it_works.py` 新增 P14 检查 `check_model_switch`：控制台配 `--model-config-dir`，
   `GET /api/model-config` 读默认 → `PUT /api/model-config` 换模型 → 之后按需加载的新 agent 用新模型，
   以 `model.call` 审计的 `target` 佐证（旧 agent 用 `litellm:openai/proof-stub`，新 agent 用
   `litellm:openai/proof-stub-2`）。
2. 补一条优先级用例 `test_explicit_spec_beats_default_override`：显式 `build_model(spec)` 优先于全局
   默认 override（ADR-0040 优先级第 1 级对第 2 级）。
3. 权限（`model.read`/`model.write`）与优先级第 2 对第 3 级已由 SLICE-230/231 覆盖
   （`test_set_default_model_priority`、`test_model_config_get_requires_model_read`、
   `test_model_config_put_admin_only`），本切片只补缺。

## 契约（先改）

- 无对外接口变更。`prove_it_works.py` 是验收脚本，非框架库接口；`docs/contracts/console.md` 的
  `/api/model-config` 契约已随 SLICE-231 落地，本切片不改。

## 完成判据

- [x] 优先级第 1 对第 2 级：显式 spec 不随 override 变 -> `test_explicit_spec_beats_default_override`
- [x] e2e：换配置后新 chat 用新模型 -> `prove_it_works.py --only P14` 全绿
- [x] 全量门禁通过

## 反例

- 本切片是验收，无新行为要红：基线 `131ae75` 上 `--only P14` 报 `unknown check`（检查不存在），
  `test_explicit_spec_beats_default_override` 因用例不存在而「未收集」。P14 与用例落地后即绿，属
  「验证既有行为」而非「先红后绿」——按切片清单在本节如实说明。

## 5 问威胁建模

1. **数据**：模型字符串；P14 用本地 stub，无外部 API key。
2. **调用方**：控制台 `/api/model-config`（SLICE-231 已加 `model.read`/`model.write`）。
3. **信任边界**：单控制台进程内 override，P14 证明单副本动态生效（ADR-0040 第二阶段才跨副本）。
4. **恶意输入最坏结果**：P14 只写合法 provider 前缀；非法前缀由 SLICE-231 的 `is_valid_model_spec`
   拒绝，本切片不新增攻击面。
5. **失败是否泄露信息**：不泄露；`target` 是 provider/model 名，非敏感。

## 范围外

- 多副本同步（ADR-0040 第二阶段）。
- 进程启动时读 store 初始化 override 的独立验证（P14 的 GET 直接读 store，已覆盖读路径）。

## 证据

- `docs/evidence/SLICE-232-model-switch-verify.txt`
