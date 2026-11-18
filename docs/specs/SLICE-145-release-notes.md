# SLICE-145 v0.1.0 发布说明

状态: gated
依据: 会话确认的发布方式：先写发布说明，再打 tag；镜像只本地构建验证，不推 registry。

## 意图

1. 新增 `docs/releases/v0.1.0.md`：包含内容、安装、升级说明、已知缺口、发布验证与后续方向。
2. 发布说明与 `pyproject.toml` 的版本一致；版本变化时缺文件会让测试失败。
3. 说明里不放未填写的模板占位（`TODO`/`TBD`），已知缺口与 PROGRESS 对齐。

## 契约（先改）

- 无对外接口变化；这是发布文档切片。

## 完成判据

- [x] `docs/releases/v<version>.md` 存在 -> `test_release_notes_exist_for_the_project_version`
- [x] 发布说明包含内容、安装、升级、已知缺口与发布验证 -> `test_release_notes_cover_the_required_sections`
- [x] 没有未填写的占位 -> `test_release_notes_have_no_unfilled_placeholders`
- [x] 全量门禁通过

## 反例

- [x] 先加用例、未加说明文件时第一个用例失败（基线 `dadd75c` 上用例尚未存在）
- [x] 版本升到 0.2.0 而不加说明会让第一个用例失败

## 5 问威胁建模

1. **数据**：发布说明与版本号，不含密钥。
2. **调用方**：安装该版本的运维。
3. **信任边界**：无；文档不执行。
4. **恶意输入最坏结果**：说明误导升级（缓解：升级说明与证据索引指向实际文档）。
5. **失败是否泄露信息**：不适用。

## 范围外

- 打 tag、GitHub Release 与镜像推送（单独确认后执行）。
- 英文版发布说明。

## 证据

- `docs/evidence/SLICE-145-release-notes.txt`
