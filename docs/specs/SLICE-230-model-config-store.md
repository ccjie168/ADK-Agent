# SLICE-230 模型配置类型与 store

状态: gated
依据: ADR-0040 MVP 第 1 项（配置类型 + store + override 优先级）

## 意图

1. 新增 `ModelConfigStore` 协议（`get` / `put`，全局默认模型字符串，无租户维度）与
   `ModelConfigStoreUnavailable` 异常，放 `models/config_store.py`。
2. 文件实现 `FileModelConfigStore`（`<root>/model.txt`，原子写）与 Postgres 实现
   `PostgresModelConfigStore`（`adk_model_config` 单行 jsonb），复用 registry 的 `safe_join` /
   `LazyPool` 模式。
3. `models/__init__.py` 新增模块级 `_default_model_override` 与 `set_default_model(spec)`；
   `_default_model_config()` 读 override 优先于 `ADK_AGENT_MODEL` 与 fallback（优先级 2/3/4 落地）。

## 契约（先改）

- 无对外接口变更；`ModelConfigStore` 是框架内部端口。`docs/contracts/console.md` 的
  `/api/model-config` 属 SLICE-231，本切片不动。

## 完成判据

- [x] override 优先于环境变量 -> `test_set_default_model_priority`
- [x] 文件 store 往返 -> `test_file_model_config_store_roundtrip`
- [x] 全量门禁通过

## 反例

- 基线 `c469261`：`models` 没有 `set_default_model` / `_default_model_override`，没有
  `ModelConfigStore`，两个用例分别 `AttributeError` / `ImportError`。

## 5 问威胁建模

1. **数据**：一个模型字符串，无敏感信息。
2. **调用方**：控制台（后续 SLICE-231 的 `/api/model-config`）。
3. **信任边界**：进程内 override 变量；store 写入是 admin 路径（SLICE-231 落地）。
4. **恶意输入最坏结果**：非法模型字符串。缓解：`set_default_model` 经 `_normalize` 校验 provider
   前缀，非法值在 `build_model` 时 fail-closed。
5. **失败是否泄露信息**：store 读失败抛 `ModelConfigStoreUnavailable`，不泄露细节。

## 范围外

- 控制台 `/api/model-config` 端点与管理员 UI（SLICE-231）。
- 多副本同步（ADR-0040 第二阶段）。
- `prove_it_works` 验收（SLICE-232）。

## 证据

- `docs/evidence/SLICE-230-model-config-store.txt`
