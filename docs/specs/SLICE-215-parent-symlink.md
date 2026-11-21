# SLICE-215 目录摄取逐段打开路径

状态: gated
依据: PROGRESS 已知缺口第 9 条、SLICE-212 复核留下的残余（父目录被换入符号链接时 `O_NOFOLLOW` 只约束末段）。

## 意图

1. 目录模式从摄取根目录开始，按相对路径逐段用 `dir_fd` 打开目录，每段都带 `O_NOFOLLOW`；文件本身同样
   不跟随符号链接。列出目录之后把任一父目录换成符号链接，打开会失败，整次命令退出 1。
2. 传入的路径不在根目录下时直接拒绝，不依赖平台的 `dir_fd` 支持。
3. Windows 没有 `O_NOFOLLOW`/`O_DIRECTORY`，退化为现有的单次打开加 `fstat`/`lstat` 复核；范围外的
   保证不变。

## 契约（先改）

- `docs/contracts/cli.md` 的 `rag ingest` 目录模式把「打开时不跟随符号链接」的范围从末段扩到每个路径段，
  并保留 Windows 的平台差异说明。

## 完成判据

- [x] 根目录外的路径被拒绝 -> `test_read_rag_file_rejects_a_path_outside_the_root`
- [x] 父目录换入符号链接后打开失败 -> `test_read_rag_file_refuses_a_swapped_parent_directory`（POSIX）
- [x] 常规目录摄取不变 -> 既有目录用例
- [x] 全量门禁通过

## 反例

- 基线 `f0eba3f`：`_read_rag_file` 不接收 `root`，新用例 `TypeError` 失败；父目录换入后
  `O_NOFOLLOW` 只挡住末段，仍会读到根目录之外。
- 本机 Windows 没有创建符号链接的权限，父目录用例在本机跳过，只在 Linux CI 运行；红态以根目录外
  路径用例为准。

## 5 问威胁建模

1. **数据**：被摄取进检索库的本地文件内容。
2. **调用方**：运维的 `rag ingest --dir`。
3. **信任边界**：本地目录内容（可能被同机低权限进程改动）→ 检索库。
4. **恶意输入最坏结果**：列目录后把某个父目录换成指向敏感目录的符号链接，摄取器读到根目录之外的文件
   并写进检索库。缓解：逐段 `O_NOFOLLOW` 打开，父目录在打开时被拒绝，命令退出 1。
5. **失败是否泄露信息**：只输出相对路径与异常类型。

## 范围外

- Windows 上的句柄级等价保证。
- 目录级增量同步。

## 证据

- `docs/evidence/SLICE-215-parent-symlink.txt`
