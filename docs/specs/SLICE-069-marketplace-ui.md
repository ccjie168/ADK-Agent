# SLICE-069 市场视图与工件状态（UI-3）

状态: planned
依据: ADR-0008，SLICE-066，SLICE-068，`docs/contracts/console.md`。

## 意图（要什么，不写怎么写）

工件链已经闭环，但浏览器里看不到。这一刀把注册表页做成租户内市场：每个已发布版本显示工件摘要与验签状态，详情区展示 manifest 和工件信息，并能把已加载的 agent 切到聊天页。

- 控制台接受可信密钥（`--artifact-keys`/`ADK_ARTIFACT_KEYS`），`/api/registry` 每个条目增加 `artifact`：摘要、大小、`key_id`、`status`。
- `status` 取值 `verified`、`untrusted`、`unknown`、`unsigned`；没有工件时为 `null`。
- 前端注册表表格加 artifact 列，状态用徽标；详情区显示工件信息，提供"Open chat"（agent 没在当前控制台加载时给出提示）。
- 不新增按需加载版本的能力；"Open chat"只对启动时已加载的 agent 生效。
- 提供演示基建：`scripts/demo_seed.py` 造两个带工件的发布和一个待审批请求；`docs/demo/pilot-demo.md` 是五分钟演示脚本。
- 用无头浏览器截图作为 UI 证据：`docs/evidence/ui/SLICE-069-marketplace.png`。

## 新增文件

- `tests/test_console_marketplace.py`
- `scripts/demo_seed.py`
- `docs/demo/pilot-demo.md`
- `docs/evidence/ui/SLICE-069-marketplace.png`
- `docs/evidence/SLICE-069-marketplace-ui.txt`

## 修改文件

- `src/adk_agent/console.py`：`artifact_trust`、列表字段、前端表格与详情
- `src/adk_agent/cli.py`：`_artifact_trust` 与接线
- `docs/contracts/console.md`
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 数据形状

```text
RegistryEntry += "artifact": null | {
  "digest": "sha256:<hex>",
  "size": int,
  "key_id": str | null,
  "status": "verified" | "untrusted" | "unknown" | "unsigned"
}

status:
  无工件                -> null
  无 signature/key_id   -> unsigned
  未配置 TrustStore     -> unknown
  TrustStore.verify 通过 -> verified
  ArtifactTrustError    -> untrusted
```

## 完成判据（可执行）

- [ ] 可信签名显示 verified -> `tests/test_console_marketplace.py::test_listing_includes_verified_artifact`
- [ ] 错误密钥显示 untrusted -> `tests/test_console_marketplace.py::test_untrusted_status`
- [ ] 未配置密钥显示 unknown -> `tests/test_console_marketplace.py::test_unknown_without_trust`
- [ ] 未签名显示 unsigned -> `tests/test_console_marketplace.py::test_unsigned_status`
- [ ] 无工件为 null -> `tests/test_console_marketplace.py::test_no_artifact`
- [ ] CLI 把密钥文件接成 TrustStore -> `tests/test_console_marketplace.py::test_cli_wires_trust`
- [ ] 非法密钥文件退出 1 -> `tests/test_console_marketplace.py::test_cli_rejects_bad_keys`
- [ ] 演示脚本可生成注册表与审批 -> 手工执行 `scripts/demo_seed.py`
- [ ] 截图写入 `docs/evidence/ui/` -> 证据文件
- [ ] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [ ] 反例 1：`build_console_app(..., artifact_trust=...)` -> 当前 `TypeError`
- [ ] 反例 2：`/api/registry` 没有 `artifact` 字段 -> 当前条目缺字段，测试 `KeyError`
- [ ] 反例 3：未配置可信密钥却显示 `verified` -> `test_unknown_without_trust`

## 契约（如涉及对外接口）

先改契约，已改 `docs/contracts/console.md` 的 `GET /api/registry`。

## 5 问威胁建模（10 分钟）

1. **数据**：工件摘要、大小、`key_id`、验签结论；manifest 与评测报告。
2. **调用方**：浏览器控制台用户。
3. **信任边界**：控制台到注册表；可信公钥配置。
4. **恶意输入最坏结果**：把不可信工件显示成已验证（缓解：`unknown` 与 `untrusted` 分开显示，未配置密钥不猜）；跨租户浏览（沿用现有 403）；公钥文件内容泄露（只读文件，不回显）。
5. **失败是否泄露信息**：状态是固定枚举；错误沿用既有错误码。

## 范围外

- 按需加载未启动的版本。
- 从 UI 发布工件。
- 工具目录（UI-4）。
- 前端工程化与构建链。

## 证据

- 反例红: 待补
- 实现后绿: 待补
- 实机: 待补
- 截图: 待补
