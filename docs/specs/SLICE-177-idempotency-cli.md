# SLICE-177 工具网关幂等存储 CLI 接线

状态: gated
依据: ADR-0034 决定 3 的收尾：把幂等存储接入 `serve-tool-gateway`，使生产可用。

## 意图

1. `cli.py` 增加 `_idempotency_store(args)`：从 `--idempotency-dir` 或 `--idempotency-db` 构建
   `FileToolIdempotencyStore`/`PostgresToolIdempotencyStore`，两者互斥，都不给返回 None。
2. `serve-tool-gateway` 增加 `--idempotency-dir`/`--idempotency-db` 参数，并把 store 传给
   `FunctionToolGateway(idempotency=...)`。

## 契约（先改）

- 无对外 schema 变更；CLI 帮助文本随参数新增。

## 完成判据

- [ ] 无参数返回 None -> `test_idempotency_store_none_without_flags`
- [ ] `--idempotency-dir` 构建文件存储 -> `test_idempotency_store_file`
- [ ] `--idempotency-db` 构建 Postgres 存储 -> `test_idempotency_store_postgres`
- [ ] 同时给两者退出 1 -> `test_idempotency_store_rejects_both`
- [ ] `serve-tool-gateway --help` 含新参数 -> `test_serve_tool_gateway_help_lists_idempotency_flags`
- [ ] 全量门禁通过

## 反例

- [ ] 基线（未实现）上 `cli.py` 无 `_idempotency_store`，`serve-tool-gateway` 无幂等参数

## 5 问威胁建模

1. **数据**：幂等存储的位置（目录或 Postgres URL）。
2. **调用方**：`serve-tool-gateway` 操作员。
3. **信任边界**：CLI 参数到存储构造。
4. **恶意输入最坏结果**：目录与 URL 混用导致不确定后端（缓解：互斥退出 1）。
5. **失败是否泄露信息**：仅退出码与提示，不泄露 URL 明文。

## 范围外

- `idempotency_ttl_seconds` 的 CLI 开关（沿用默认 86400）。
- 记录归档与过期清理。

## 证据

- `docs/evidence/SLICE-177-idempotency-cli.txt`
