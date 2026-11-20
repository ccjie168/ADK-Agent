# SLICE-195 RAG CLI 收尾：安装提示、分级单一来源、目录摄取

状态: gated
依据: SLICE-194 验证记录的三条非阻塞项与 PROGRESS 缺口清单第 9 条。

## 意图

1. 未安装 `litellm` extra 时，`rag` 给出可操作的安装提示，而不是只报 `rag failed: ModuleNotFoundError`。
2. `--data-class` 的可选值从 `core.policy.DataClass` 推导，不再手写重复的元组，避免改枚举时漂移。
   这一项没有可写的红态：基线元组与新实现取值完全相同，任何断言都会在基线上绿。按切片规则不写绿于
   基线的测试，改为在证据里记录推导方式与人工核对结论。
3. `rag ingest --dir DIR` 批量摄取目录：按相对路径排序、逐个文件调用既有摄取管线，
   `source_id` 取相对路径（POSIX 分隔符），空文件跳过并在 stderr 记录。

## 契约（先改）

- `docs/contracts/cli.md` 的 `rag ingest` 一节：`--text` 与 `--dir` 互斥；`--source-id` 只在
  `--text` 模式必填，与 `--dir` 同时给出退出 2；目录模式的 `source_id`、排序、空文件与失败语义；
  汇总输出形状 `{"tenant","sources","chunks"}`；缺 `litellm` extra 时的提示文案。

## 完成判据

- [x] 缺 `litellm` 时提示安装 extra -> `test_rag_ingest_reports_missing_litellm_extra`
- [x] 目录模式按相对路径写入各来源 -> `test_rag_ingest_directory_ingests_relative_source_ids`
- [x] 目录模式跳过空文件并继续 -> `test_rag_ingest_directory_skips_empty_files`
- [x] `--text` 缺 `--source-id` 退出 1 -> `test_rag_ingest_requires_source_id_without_dir`
- [x] `--dir` 与 `--source-id` 同时给出退出 2 -> `test_rag_ingest_rejects_source_id_with_dir`
- [x] 全量门禁通过

## 反例

- [x] 基线上 `--dir` 不是合法参数（argparse 退出 2）
- [x] 目录里放一个空文件时，若不跳过，摄取会在第一个空文件处退出 1

## 5 问威胁建模

1. **数据**：被摄取目录下的文件正文与向量；相对路径进入 `source_id`。
2. **调用方**：持有数据库 DSN 与模型通道凭据的运维人员或批处理作业。
3. **信任边界**：目录路径 → 读取范围；文件名 → `source_id` 列。
4. **恶意输入最坏结果**：指向 `/` 之类的目录导致读取宿主大量文件，或目录里的符号链接把读取引到根目录之外。
   缓解：只收根目录下解析后的普通文件，跳过符号链接；不跟随 `..`；一次只处理真实文件，工具不做删除。
5. **失败是否泄露信息**：错误只含相对路径与异常类型，不回显正文、DSN 与模型凭据。

## 范围外

- 增量同步、删除已消失来源、并发摄取。
- `serve-*` 与运行路径的检索接线（另立 ADR）。
- 真实环境验证（运维验收项）。

## 证据

- `docs/evidence/SLICE-195-rag-cli-cleanup.txt`
