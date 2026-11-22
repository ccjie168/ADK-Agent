# SLICE-222 控制台 UI 视觉基线

状态: gated
依据: ADR-0039 MVP 第 1 项（视觉基线先行，供后续六个切片复用）

## 意图

1. 在控制台 `_INDEX_HTML` 的 `<style>` 里建立统一的设计 token（圆角、阴影、间距），浅色优先：
   在现有 `:root` 变量之外新增 `--radius-sm` / `--radius-lg` / `--shadow-card` /
   `--shadow-card-hover` / `--space-1` 到 `--space-4`。
2. 建立通用的指标卡片系统 `.metric-grid`（响应式网格）与 `.stat-card`（统计卡片），以及
   `.stat-label` / `.stat-value` / `.stat-delta` 三个子元素样式，供后续总览页与能力面板复用。
3. 不新增任何面板、不新增后端接口、不改对外契约；只落地可复用的视觉骨架。

## 契约（先改）

无对外接口变更，不改 `docs/contracts/`。设计 token 与卡片 class 是控制台内部视觉骨架，不是对外契约。

## 完成判据

- [x] 首页 HTML 含新增设计 token -> `test_index_has_design_tokens`
- [x] 首页 HTML 含指标卡片系统 class -> `test_index_has_metric_card_system`
- [x] 全量门禁通过

## 反例

- 基线 `bf92850`：`_INDEX_HTML` 的 `<style>` 里没有 `--radius-lg` / `--shadow-card`，也没有
  `.metric-grid` / `.stat-card`，两个新用例分别 `AssertionError`。

## 5 问威胁建模

1. **数据**：无用户数据，纯静态 CSS / HTML 骨架。
2. **调用方**：浏览器加载 `GET /`，不新增端点。
3. **信任边界**：无，纯展示层。
4. **恶意输入最坏结果**：无输入面；CSS class 只是静态标记，不引入脚本执行。
5. **失败是否泄露信息**：无。

## 范围外

- 总览首页、各能力面板（SLICE-223 起）。
- 通用导入、Ask AI（SLICE-227 / 228）。
- 前端框架、构建链（ADR-0039 已否决）。

## 证据

- `docs/evidence/SLICE-222-console-ui-visual-baseline.txt`
