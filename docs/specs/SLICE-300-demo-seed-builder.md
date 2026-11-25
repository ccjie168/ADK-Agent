# SLICE-300 演示种子补平台构建签名

状态: active
依据: SLICE-291（ADR-0044）在载入侧强制 `in_process` 工件的构建信任，演示脚本未跟进

## 意图

`scripts/demo_seed.py` 生成的 `in_process` 演示工件只有发布签名，没有平台构建签名；
按脚本打印的步骤启动控制台并 `--agent-ref` 载入时会因缺少构建信任失败。本切片让脚本
同时写 `builder_signature`/`builder_key_id`，并在输出与演示手册里给出
`ADK_BUILDER_KEYS` 与 `--builder-keys`。演示仍使用同一把本地演示密钥，
生产语义不变（平台构建私钥仍不应落在演示目录之外的使用场景）。

## 契约（先改）

演示脚本不是对外接口，但 `docs/demo/pilot-demo.md` 的启动步骤会变：

- `keys.json` 同时作为发布信任与构建信任的公钥来源；
- 输出增加 `export ADK_BUILDER_KEYS="$(cat demo/keys.json)"` 与
  `--builder-keys demo/keys.json`；
- 手册「把已有 Agent 跑起来」一节同步这两行。

## 完成判据

- [ ] `in_process` 工件带可验证的 builder 签名 -> `test_demo_seed_signs_builder`
- [ ] 种子工件可用 `--builder-keys` 载入 -> `test_demo_seed_artifact_loads_with_builder_trust`
- [ ] 输出与手册给出构建信任的导出与参数 -> `test_demo_seed_prints_builder_flags`
- [ ] `--full` 门禁通过

## 反例

master 上脚本产出的 `AgentArtifact.builder_signature` 为 `None`，`load_agent` 在
`in_process` 且无构建信任时抛 `ArtifactLoadError`；测试在 master 上失败。

## 5 问威胁建模

1. **数据**：演示发布私钥与公钥，仅本地演示目录；不新增密钥材料。
2. **调用方**：脚本由开发者手动运行；载入仍要求控制台显式信任构建公钥。
3. **信任边界**：构建签名绑定工件 digest；演示密钥与生产密钥分离，手册注明仅用于演示。
4. **恶意输入**：脚本只读自身生成的目录；参数只有 root/tenant。
5. **失败是否泄露信息**：失败仍是既有 `ArtifactLoadError` 文案，不含路径以外的内容。

## 范围外

- 为演示生成独立的生产级构建密钥（演示专用一把密钥已足够）。
- 控制台 UI 的种子数据。
- 同刻审计 1000 条窗口（另一切片）。

## 证据

- `docs/evidence/SLICE-300-demo-seed-builder.txt`
