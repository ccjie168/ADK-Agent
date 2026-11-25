# SLICE-294 控制台使用手册（HTML）

状态: active
依据: 用户 2026-11-25 反馈「应用复杂、不知道如何使用」，并要求以 HTML 形式提供便于阅读的说明

## 意图

写一份单文件 HTML 使用手册，并在控制台挂在 `/guide`：手机经隧道打开
`https://<host>/guide` 即可阅读，不需要登录、不依赖外部资源。手册按任务组织：
导航地图、逐页用途与前置条件、两条完整流程、权限与错误对照。

内容源是 `docs/guides/console-ui.md` 的等价 HTML 版本；不再维护 Markdown 副本，
避免两份文档漂移。

## 契约（先改）

`docs/contracts/console.md` 的前端壳一节加 `GET /guide`：返回
`docs/guides/console-ui.html`，无需鉴权；文件缺失返回 404 `guide_not_found`。

## 完成判据

- [ ] `GET /guide` 返回 HTML 手册 -> `test_guide_route_serves_the_html`
- [ ] `/guide` 不需要令牌 -> `test_guide_route_is_open_without_a_token`
- [ ] 手册文件缺失时返回 404 -> `test_guide_route_404_when_missing`
- [ ] 手册覆盖全部 27 个路由 -> `test_guide_documents_every_route`
- [ ] 手册自包含，无外部脚本与样式 -> `test_guide_is_self_contained`
- [ ] 手册含常见错误对照 -> `test_guide_covers_common_errors`
- [ ] 侧栏「设置」组有使用说明入口 -> `test_sidebar_links_the_guide`
- [ ] 桌面与 390px 截图留证 -> 证据
- [ ] `web/dist/` 重建
- [ ] `--full` 门禁通过

## 反例

实现前控制台没有 `/guide` 路由，手册文件不存在；七个用例在 master 上全部失败。

## 5 问威胁建模

1. **数据**：静态使用说明；不含密钥、内部路径或运行时数据。
2. **调用方**：所有能访问控制台地址的主体，包括未登录用户。
3. **信任边界**：文档是公开静态资源；不读取任何存储，不接受参数。
4. **恶意输入**：无输入参数；文件缺失返回固定 404，不回显路径。
5. **失败是否泄露信息**：404 `guide_not_found` 不暴露文件系统路径。

## 范围外

- 界面内的上下文帮助气泡与视频。
- 手册的多语言版本。
- 把手册内容生成进 Vue 包（保持独立 HTML，便于直接分享）。

## 证据

- `docs/evidence/SLICE-294-console-guide.txt`
- `docs/evidence/ui/SLICE-294/`
