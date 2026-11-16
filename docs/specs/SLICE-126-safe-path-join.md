# SLICE-126 文件存储路径加固

状态: gated
依据: SLICE-125 的 6 条 `py/path-injection` 按同型误报关闭，用户要求把共享 `safe_join` 落到所有文件存储，作为第二道防线并让后续同类告警要么消失、要么一眼可审。

## 意图（要什么，不写怎么写）

新增一个路径拼接 helper。每个路径段先做安全名校验，再解析真实路径并确认仍在存储根目录之下。所有文件存储的 `_path` 改用它。

- 校验规则保持各存储现有字符集不变，只是集中到一处。
- 解析后的包含性检查防住符号链接与未来漏用的调用点。
- 失败抛统一的 `UnsafePath`，调用方按现有 `ValueError` 语义处理。
- 不改变任何存储布局、文件名或对外接口。

## 数据形状

`src/adk_agent/registry/paths.py`：

- `UnsafePath(ValueError)`。
- `safe_join(root: str | Path, *parts: str, pattern: str = _DEFAULT) -> Path`
  - 每个 `part` 必须全匹配 `pattern`，默认 `^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$`。
  - 拼接后对根目录与目标做 `resolve(strict=False)`，目标必须是根的相对路径；否则抛 `UnsafePath`。
  - 返回未解析的拼接路径，保持现有文件名与符号链接语义。
- 存储如有更严格的字符集（例如 trigger id 只允许 `-`），传入自己的 `pattern`。

## 迁移范围

`src/adk_agent/registry/` 下所有用名字拼路径的文件存储，以及 `src/adk_agent/approvals.py`：

- `file.py`、`credentials.py`、`connectors.py`、`connector_requests.py`、`triggers.py`、`trigger_runs.py`、`lifecycle.py`、`tool_grants.py`、`peers.py`、`peer_grants.py`、`remote_agents.py`、`reports.py`、`artifacts.py`、`approvals.py`。
- `artifacts.py` 的 digest 路径也走同一 helper，传入 digest 的 hex 部分。
- 不改布局；迁移后现有文件名保持不变。

## 新增文件

- `src/adk_agent/registry/paths.py`
- `tests/registry/test_paths.py`
- `docs/evidence/SLICE-126-safe-path-join.txt`

## 修改文件

- 上述文件存储的 `_path` 实现
- `src/adk_agent/registry/__init__.py`（导出 `safe_join`、`UnsafePath`）
- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 合法段拼出原路径 -> `tests/registry/test_paths.py::test_valid_parts_join`
- [x] `..`、绝对路径、反斜杠、冒号、前导点、空段、超长段被拒 -> `::test_unsafe_parts_are_rejected`
- [x] 指向根目录外的符号链接被拒 -> `::test_symlink_escape_is_rejected`（无符号链接权限时跳过）
- [x] 不存在的嵌套路径正常解析 -> `::test_missing_paths_resolve_under_root`
- [x] 迁移后现有存储测试全绿，文件名不变 -> 既有 registry、approvals 测试
- [x] 全量门禁通过 -> `scripts/check.py --fast` 与 `scripts/check.py --full`

## 反例（必须在实现前跑红）

- [x] 反例 1：`safe_join` 接受 `../escape` -> 期望 `::test_unsafe_parts_are_rejected` 失败
- [x] 反例 2：根目录内的符号链接指向外部仍放行 -> 期望 `::test_symlink_escape_is_rejected` 失败
- [x] 反例 3：迁移后文件名变化或旧测试失败 -> 期望既有存储测试失败

红态记录: 实现前 `tests/registry/test_paths.py` 报 `cannot import name 'UnsafePath'`。

## 5 问威胁建模（10 分钟）

1. **数据**：租户、agent/trigger/connector/credential 名、版本、请求 id、digest 与文件名后缀。
2. **调用方**：各文件存储的读写方法；部分名字来自经过认证的请求或 CLI。
3. **信任边界**：名字到磁盘路径；存储根目录到操作系统。
4. **恶意输入最坏结果**：路径穿越读写根目录外文件（缓解：字符集全匹配 + 解析后包含性检查）；符号链接逃逸（缓解：`resolve` 后必须是根的子路径）；未来新存储漏用校验（缓解：统一 helper，代码审查只需看一处）；迁移改变文件名导致数据不可见（缓解：迁移不改布局，既有测试保护）。
5. **失败是否泄露信息**：异常只含「unsafe path」与段名，不含绝对路径、根目录或文件内容。

## 范围外

- 引入外部路径库或新依赖。
- 改变存储布局、加密或权限模型。
- 非文件存储的后端（Postgres）路径语义。
- 调度循环与重试（SLICE-127）。

## 证据

- 红态、实现后绿与门禁结果: `docs/evidence/SLICE-126-safe-path-join.txt`
