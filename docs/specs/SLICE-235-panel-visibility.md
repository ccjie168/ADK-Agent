# SLICE-235 只读面板可见性收紧

状态: gated
依据: 用户 2026-11-23 确认「同意」：quota/rag/model/semantics/overview 面板从 `runs.read`（基础）收为
operator 及以上可见。

## 意图

1. 新增能力 `ops.read`（admin + operator），门控平台运营只读数据：overview、quota、rag、semantics。
2. model 面板复用已有的 `model.read`（admin + operator，SLICE-231）。
3. 服务端给 `/api/overview`、`/api/quota`、`/api/rag`、`/api/semantics`、`/api/model` 加能力检查
   （principal 解析后第一条语句）；前端把对应 tab/section 的 `data-capability` 改为 `ops.read` /
   `model.read`，并在 connect 与 SSE tick 里按能力跳过加载。

## 契约（先改）

- `docs/contracts/console.md`：`/api/overview`、`/api/quota`、`/api/rag`、`/api/semantics` 注明需
  `ops.read`；`/api/model` 注明需 `model.read`；能力清单描述补 `ops.read`。

## 完成判据

- [x] overview/quota/rag/semantics 缺 `ops.read` 403 -> `test_ops_read_panels_require_ops_read`
- [x] model 缺 `model.read` 403 -> `test_model_panel_requires_model_read`
- [x] 能力清单含 `ops.read`（admin+operator）-> `test_console_me.py` 更新
- [x] 全量门禁通过

## 反例

- 基线 `bb264cf`：requester 调 `/api/overview`/`/api/quota`/`/api/rag`/`/api/model` 返回 200、
  `/api/semantics` 返回 404（未配置），期望 403。加用例、未改实现时失败。

## 5 问威胁建模

1. **数据**：平台运营指标（配额、检索、模型调用、语义表）。
2. **调用方**：控制台浏览器。
3. **信任边界**：`ops.read` admin+operator；`model.read` admin+operator。
4. **恶意输入最坏结果**：基础角色读运营指标。缓解：能力检查前置。
5. **失败是否泄露信息**：403 固定 `forbidden`。

## 范围外

- ask-ai 与 import 面板仍 `runs.read`（基础可见；import 动作已由 SLICE-234 按写能力门控）。
- overview 卡片内的 null 门控仍保留（operator+ 里缺具体卡片能力的仍见 null）。

## 证据

- `docs/evidence/SLICE-235-panel-visibility.txt`
