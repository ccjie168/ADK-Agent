# SLICE-154 工件内 manifest 与发布记录的绑定

状态: gated
依据: PROGRESS 缺口清单第 7 条：构建签名只绑定工件 digest，HTTP 注册表发布可把已有平台工件
配到不同租户/id/工具授权的记录上；CLI 发布会比较工件内 manifest 与记录 manifest，HTTP 端不比较。

## 意图

1. 上传工件字节时，服务端读取 zip 内的 `manifest.json`，必须与所有租户中引用该 digest 的记录
   manifest 完全一致（先按调用方可见范围找到记录，再全租户扫描复核）；无法解析或任一记录不一致
   返回 400 `artifact_manifest_mismatch`，字节不写入存储。
2. 发布记录时，如果该 digest 的字节已经存在（先上传后发布），同样解析并比较；不一致返回
   400 `artifact_manifest_mismatch`。字节尚未上传时跳过，由上传端补查。
3. 正常顺序（先发布记录、后上传字节）与 CLI 的既有行为不变；`read_artifact_zip` 的解析逻辑
   抽成 `read_artifact_manifest`，行为不变。
4. 契约先更新 `POST /v1/agents`、`PUT /v1/artifacts/{digest}` 与错误表。

## 契约（先改）

- `docs/contracts/registry_service.md` 的发布、上传与错误码。

## 完成判据

- [x] 记录 manifest 与工件内 manifest 不同时上传被拒且不落盘 -> `test_upload_rejects_bytes_with_a_different_manifest`
- [x] 先上传字节、再发布不匹配的记录被拒 -> `test_publish_rejects_a_record_mismatching_stored_bytes`
- [x] 其他租户的同 digest 不匹配记录也会阻止上传 -> `test_upload_checks_records_beyond_the_caller_tenant`
- [x] 匹配路径保持可用 -> `test_upload_artifact`
- [x] 全量门禁通过

## 反例

- [x] 基线用真实 zip 上传到一条 manifest 不同的记录返回 201 并写入存储
- [x] 基线在字节已存在时发布 manifest 不同的记录返回 201
- [x] 基线只比对调用方租户的记录，跨租户伪造记录可通过上传复核

## 5 问威胁建模

1. **数据**：工件字节、工件内 manifest、发布记录 manifest、构建与工件签名。
2. **调用方**：持有 admin 或同租户 token 的发布者。
3. **信任边界**：HTTP 请求到注册表存储；工件字节与 manifest 都来自调用方。
4. **恶意输入最坏结果**：把已签名平台工件配到不同租户/工具授权的记录（缓解：两侧都要求
   工件内 manifest 与记录 manifest 完全一致）；伪造 zip 内 manifest 换取信任（缓解：字节
   摘要与签名仍先校验，比较只收紧不放松）。
5. **失败是否泄露信息**：固定错误码，不回显 manifest 内容。

## 范围外

- 构建签名本身绑定 manifest（需要新签名格式，另行评审）。
- 无工件的元数据记录不涉及字节比较。
- 历史已存在的不一致记录不自动修复。

## 证据

- `docs/evidence/SLICE-154-artifact-manifest-binding.txt`
