# SLICE-212 目录摄取不跟随换入的符号链接

状态: gated
依据: PROGRESS 已知缺口第 9 条（`is_symlink` 与 `read_text` 之间有 TOCTOU 窗口）。

## 意图

1. 目录模式列出的文件在打开时用 `O_NOFOLLOW`（POSIX），并在打开后确认是普通文件。列目录之后被换成
   符号链接的文件按读取失败处理，退出 1，不会读到根目录之外的目标。
2. 单文件模式（`--text FILE`）是操作员显式指定的路径，行为不变。
3. Windows 没有 `O_NOFOLLOW`，打开时会跟随符号链接；列出时的 `is_symlink` 检查保留，手册写明这条平台
   差异，不做夸大。

## 契约（先改）

- `docs/contracts/cli.md` 的 `rag ingest` 目录模式补一条：打开时用 `O_NOFOLLOW`，列目录后被换入的
  符号链接按读取失败退出 1；Windows 无此标志，仍只做列出时检查。

## 完成判据

- [x] 打开时拒绝符号链接 -> `test_read_rag_file_refuses_symlink`
- [x] 普通文件仍可读取 -> `test_read_rag_file_reads_regular_file`
- [x] 路径被换成符号链接时拒绝 -> `test_read_rag_file_rejects_a_path_that_is_now_a_symlink`
- [x] 列目录后换入的符号链接让摄取失败 -> `test_directory_ingest_fails_closed_on_swapped_symlink`
- [x] 全量门禁通过

## 反例

- 基线 `817cf11`：`_read_rag_file` 不存在，依赖它的两个用例 `AttributeError` 失败；`read_text` 会跟随符号链接。
- 本机 Windows 没有创建符号链接的权限（`WinError 1314`），两个真实符号链接用例在本机跳过，只在 Linux CI 上运行。
  因此本机的红态是 `2 failed, 22 passed, 3 skipped`；目录级漏洞本身由 `Path.read_text` 的跟随语义和
  `test_read_rag_file_rejects_a_path_that_is_now_a_symlink` 锁定，不把跳过用例当证据。
- 若打开后不检查普通文件，目录被换入时用例失败。

## 5 问威胁建模

1. **数据**：被摄取进检索库的本地文件内容。
2. **调用方**：运维的 `rag ingest --dir`。
3. **信任边界**：本地目录内容（可能被同机低权限进程改动）→ 检索库。
4. **恶意输入最坏结果**：列目录后把某个文件换成指向敏感文件的符号链接，摄取器读到并把内容写进
   检索库，后续被 agent 检索到。缓解：POSIX 上 `O_NOFOLLOW` 拒绝，读取失败即整次命令退出 1。
5. **失败是否泄露信息**：只输出相对路径与异常类型，不输出目标内容或绝对路径。

## 范围外

- 目录级增量同步。
- Windows 上的等价保证（需要句柄级校验，另行评估）。
- 单文件模式与 stdin 的路径检查。
- 父目录在列目录后被换成符号链接：`O_NOFOLLOW` 只约束路径末段，仍可能越界，记入后续缺口。

## 证据

- `docs/evidence/SLICE-212-ingest-no-follow.txt`
