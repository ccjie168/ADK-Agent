# SLICE-295 端到端验收脚本补齐构建信任

状态: gated
依据: 2026-11-25 在 master `1461d08` 上重跑 `prove_it_works.py` 出现 6 项失败（8 项通过）；
根因是 SLICE-291 收紧后，服务端载入 `in_process` 工件需要 `--builder-keys`，
而验收脚本只在 `serve-registry` 与 CLI `publish` 上给了构建信任集。

## 意图

给 `scripts/prove_it_works.py` 启动的每个会载入注册表工件的服务补
`--builder-keys`：`console`、`serve`、`serve-a2a`、`serve-triggers`。
脚本本身已经用构建私钥签名（`--builder-key`），缺的只是载入端信任集。

## 契约（先改）

无接口变化；`docs/guides/install-and-use.md` 已有「载入 in_process 需 --builder-keys」的说明，
本切片只修验收脚本，并在脚本注释里写明原因。

## 完成判据

- [ ] 每个带 `--artifact-keys` 的服务调用同时带 `--builder-keys` -> `test_every_service_with_artifact_keys_passes_builder_keys`
- [ ] 验收脚本重新跑出 14/14 PASS -> 证据
- [ ] `--full` 门禁通过

## 反例

修复前 2026-11-25 的重跑结果：P3、P5、P6、P7、P10、P14 六项服务启动超时或
`agent_load_failed`，其余 8 项通过。缺 `--builder-keys` 时服务在载入阶段
报 `in_process artifacts require builder trust`。

## 5 问威胁建模

1. **数据**：验收脚本的本地测试信任集；不涉及真实密钥。
2. **调用方**：只影响验收脚本自身启动的本机服务。
3. **信任边界**：构建公钥来自脚本生成的临时密钥对，与生产无关。
4. **恶意输入**：无新输入；脚本只在临时目录运行。
5. **失败是否泄露信息**：失败信息只在本地标准输出。

## 范围外

- `scripts/demo_seed.py` 的同类缺口（另行切片）。
- 生产部署的信任集分发。

## 证据

- `docs/evidence/SLICE-295-prove-builder-trust.txt`
