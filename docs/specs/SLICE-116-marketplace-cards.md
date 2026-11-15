# SLICE-116 市场卡片改版

状态: gated
依据: Registry 面板是一张八列表格，来源、信任、评测与生命周期只能逐列扫读，条目一多就很难判断一个版本能不能用。SLICE-094 合并远端条目后，本地行与远端行的字段差异也藏在空单元格里。

## 意图（要什么，不写怎么写）

把 Registry 面板从表格改成卡片网格。每张卡片一眼给出 agent 的身份、来源与四个判断徽标，选中后沿用现有详情区。

- 本地条目一张卡片，显示 id、版本、描述、发布时间与 digest 前缀。
- 远端条目一张卡片，显示 id、peer、label，不显示版本与 digest。
- 徽标覆盖四个判断，缺一不可:
  - 来源: local 或 remote。
  - 信任: 本地取 artifact.status（verified、untrusted、unsigned、unknown，无工件不显示）；远端取 trust.status（pinned、changed、unreachable），停用再补 disabled。
  - 评测: 有报告显示 eval，没有显示 no eval。
  - 生命周期: published、deprecated、retired。
- 徽标 tone 固定映射，不只靠文字: verified、pinned、eval、published 为 good；untrusted、changed、retired 为 bad；unsigned、unreachable、deprecated 为 warn；其余为 muted。
- 卡片是可聚焦的按钮，点击或按 Enter、Space 选中。选中态写入 `aria-pressed="true"`，并高亮边框。
- 选中后详情区（Manifest、Eval report、Artifact、Lifecycle）与 Open chat、Unload 行为不变。
- 没有条目时显示一句空态文案。

## 测试判据变更（已确认）

`tests/test_console_registry.py::test_panel_has_remote_controls` 断言页面含 `<th>source</th>` 与 `<th>trust</th>`，这钉的是旧表格。按 CLAUDE.md 先与用户确认，用户选择更新断言。同一测试改为断言 `id="registry-cards"` 存在、旧容器 `id="registry-body"` 不存在，`refresh-remote` 断言保留。不删除该测试，不放宽其他断言。

最初写法用页面级 `<th>source</th>` 不在页面中，但 Tools 面板也有同名列，会误伤。改为断言旧 Registry 容器消失，作用域正确，且不改动 Tools 面板。

## 数据形状

不新增接口。卡片由现有 `/api/registry` 条目派生，视图模型是纯函数 `registryCard(entry)`。徽标由一张规则表生成，每条规则给出 label、tone 与匹配条件；不再为每列写一段独立的单元格构造代码。现有 `artifactCell`、`lifecycleCell`、`trustCell` 删除。

## 新增文件

- `docs/evidence/SLICE-116-marketplace-cards.txt`
- `docs/evidence/ui/SLICE-116-marketplace-cards.png`

## 修改文件

- `src/adk_agent/console.py`（卡片网格、徽标规则、选中态）
- `tests/test_console_registry.py`（按上面的测试判据变更）
- `docs/specs/ROADMAP.md`
- `docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 页面带 `id="registry-cards"`，旧 Registry 容器不再出现 -> `tests/test_console_registry.py::test_panel_has_remote_controls`
- [x] 本地条目渲染一张卡片，四个徽标齐全 -> 浏览器证据：逐条列出卡片徽标文本
- [x] 远端条目渲染一张卡片，无版本、无 digest，带 peer 与 trust 徽标 -> 浏览器证据
- [x] tone 映射与上表一致 -> 浏览器证据：读取每个徽标的 class
- [x] 点击卡片高亮并载入详情 -> 浏览器证据
- [x] Enter 与 Space 也能选中，`aria-pressed` 随之变化 -> 浏览器证据
- [x] 描述中的标记按文本显示，不执行脚本 -> 浏览器证据：`window.__card_xss` 未被设置
- [x] 755px 视口下卡片网格不横向溢出 -> 浏览器证据：`scrollWidth` 不超过 `clientWidth`
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：面板仍是表格，没有卡片容器 -> 期望 `::test_panel_has_remote_controls` 在新断言上失败
- [x] 反例 2：卡片只显示 id，徽标缺失 -> 期望浏览器证据中实现前页面没有卡片，实现后每张卡片四类徽标齐全
- [x] 反例 3：描述用 `innerHTML` 渲染，标记被执行 -> 期望浏览器证据中 `window.__card_xss` 未设置
- [x] 反例 4：远端卡片显示版本或 digest，误导用户以为可加载 -> 期望浏览器证据中远端卡片没有这两项
- [x] 反例 5：选中态只加 CSS class，键盘无法选中 -> 期望浏览器证据中按 Enter 后 `aria-pressed` 为 true

红态记录: 实现前 `test_panel_has_remote_controls` 在 `assert 'id="registry-cards"' in response.text` 上失败；页面只有旧表格。

## 契约（如涉及对外接口）

不涉及。`/api/registry` 的请求与返回不变，契约文档不改。

## 5 问威胁建模（10 分钟）

1. **数据**：agent 描述、版本、digest、发布时间、peer 标识、生命周期状态与原因。
2. **调用方**：控制台浏览器用户、租户管理员、远端目录维护者。
3. **信任边界**：接口到浏览器；卡片文本到 DOM；选中卡片到 Open chat 与 Unload 接口。
4. **恶意输入最坏结果**：描述或 label 注入脚本导致 XSS（缓解：全部 `textContent`）；跨租户看到别人条目（缓解：沿用服务端 principal 过滤）；误点卡片直接加载 agent（缓解：选中不加载，Open chat 是独立动作，retired 仍被拒绝）；生命周期原因泄露给无权用户（缓解：只对已授权租户返回的条目渲染）。
5. **失败是否泄露信息**：注册表不可用时沿用固定错误码，卡片区为空并显示固定文案，不返回存储路径。

## 范围外

- 卡片搜索、排序、筛选与分页。
- 卡片内的快捷动作（加载、卸载、刷新），仍走选中后的现有按钮。
- 评测分数或报告摘要直接进卡片。
- 远端 agent 的加载与开聊。
- 接口字段新增或修改。

## 证据

- 红态、实现后绿、浏览器卡片与门禁结果: `docs/evidence/SLICE-116-marketplace-cards.txt`
- 亮色卡片截图: `docs/evidence/ui/SLICE-116-marketplace-cards.png`
- 深色卡片截图: `docs/evidence/ui/SLICE-116-marketplace-cards-dark.png`
