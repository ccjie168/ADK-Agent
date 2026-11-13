# SLICE-056 压测基线：配额与审计吞吐

状态: merged
依据: SLICE-044，SLICE-052，SLICE-053，`docs/PROGRESS.md` 的下一刀建议。

## 意图（要什么，不写怎么写）

配额和审计链没有可重复的压测入口，之前只有一次性手工脚本。这一刀加一个测量工具，给出可复现的基线数字，并让配额的不超卖约束在并发下可验证。

- 新增 `scripts/loadtest.py`，两个子命令 `quota` 和 `audit`。
- `quota` 用 `requests` 个任务、上限 `concurrency` 的并发去抢占配额，统计 `ok` / `denied` / `errors`、等待时长分位和峰值并发。
- `--url` 给了就打到 Postgres（`build_quota_manager`），不给就用进程内实现。默认用唯一租户名，重复运行互不影响。
- `audit` 顺序追加 `records` 条审计事件，统计每条耗时和吞吐，结束后跑一次 `verify_audit_file`。
- 两个子命令都输出一个 JSON 报告到 stdout 或 `--out`。报告有固定字段。
- 不变量不成立或输入非法时退出 1，报告仍先打印。

报告形状：

```text
{
  "scenario": "quota" | "audit",
  "started_at": "<ISO-8601>",
  "tenant": "<仅 quota>",
  "requests": int,          # 计划发起的次数
  "concurrency": int,       # 仅 quota
  "ok": int, "denied": int, "errors": int,
  "latency_ms": {"p50": float, "p95": float, "p99": float, "max": float},
  "throughput_per_s": float,
  "peak_active": int,       # 仅 quota
  "verify_records": int,    # 仅 audit
  "invariants": [{"name": str, "holds": bool}]
}
```

`latency_ms` 的样本是每次 `reserve` 进入（成功或被拒都算）以及每次 `append` 的耗时。

## 新增文件

- `scripts/loadtest.py`
- `tests/test_loadtest.py`
- `docs/evidence/SLICE-056-load-baseline.txt`

## 修改文件

- `docs/specs/ROADMAP.md`、`docs/PROGRESS.md`

## 完成判据（可执行）

- [x] 分位取最近秩，空样本返回 0 -> `tests/test_loadtest.py::test_percentiles_nearest_rank`
- [x] 报告字段齐全且数值类型正确 -> `tests/test_loadtest.py::test_quota_report_shape`
- [x] 并发抢 `max_runs` 时成功数等于上限，总数守恒 -> `tests/test_loadtest.py::test_quota_max_runs_never_oversells`
- [x] 并发峰值不超过 `max_concurrent` -> `tests/test_loadtest.py::test_quota_concurrency_peak`
- [x] 审计追加后整链校验通过，计数一致 -> `tests/test_loadtest.py::test_audit_writes_and_verifies`
- [x] 审计分段仍可校验 -> `tests/test_loadtest.py::test_audit_with_rotation`
- [x] 写入已存在的审计文件被拒且不改文件 -> `tests/test_loadtest.py::test_audit_refuses_existing_file`
- [x] `--append` 追加后整链仍可校验 -> `tests/test_loadtest.py::test_audit_append_keeps_chain`
- [x] 记录数超过上限被拒 -> `tests/test_loadtest.py::test_records_are_bounded`
- [x] 配额没有任何上限时被拒 -> `tests/test_loadtest.py::test_quota_requires_a_limit`
- [x] CLI 输出 JSON 报告 -> `tests/test_loadtest.py::test_cli_writes_report`
- [x] CLI 缺必填参数退出 2 -> `tests/test_loadtest.py::test_cli_requires_arguments`
- [x] `python scripts/check.py --fast` 全绿 -> 证据文件

## 反例（必须在实现前跑红）

- [x] 反例 1：`from loadtest import percentiles` 不存在 -> 当前 `ModuleNotFoundError`
- [x] 反例 2：`python scripts/loadtest.py quota --requests 5` -> 当前 文件不存在，退出 2
- [x] 反例 3：并发压 `max_runs=5`、`requests=50` 时若实现直接放行，成功数会大于 5 -> 由 `test_quota_max_runs_never_oversells` 覆盖（现有配额实现已正确，此测试防回归）

## 契约（如涉及对外接口）

不涉及。这是开发与运维用的测量脚本，不是对外接口，报告字段只在本文和证据里约定。

## 5 问威胁建模（10 分钟）

1. **数据**：配额计数和租约、审计事件、报告里的耗时数字和租户名。审计事件用固定测试 principal，不含业务数据。
2. **调用方**：开发者和运维，手动运行；不进 `check.py` 门禁，避免慢测试污染提交回路。
3. **信任边界**：脚本到 Postgres（DSN 来自命令行或环境变量），脚本到审计文件路径。
4. **恶意输入最坏结果**：误连生产库并写入压测租户；`--records` 过大撑爆磁盘；`--path` 指向已有审计文件导致与真实链混写。缓解：租户名固定 `loadtest-<8 位随机>` 前缀且可查；`audit` 拒绝写入已存在的路径（`--append` 才允许）；数量参数有上限。DSN 只从参数或 `LOADTEST_URL` 读，不打印。
5. **失败是否泄露信息**：报告不含 DSN，不含事件内容。错误只报异常类名。

## 范围外

- SSE 慢客户端压测，留给后续切片。
- 自动判定性能是否达标。本刀只产出基线数字，不设阈值。
- CI 定时压测。
- 多进程配额争用；`quota` 在单进程内用高并发连接逼近 advisory lock。多进程竞态已在 SLICE-044 实机里手工验证过。

## 证据

- 反例红: `docs/evidence/SLICE-056-load-baseline.txt` 的 red 段
- 实现后绿: 同文件 green 段，12 passed，ruff 全过
- 实机基线: 同文件 live 段。进程内配额 20k 次不超卖；Postgres 15.19 上 32 并发 159 次/秒、p50 215 ms；并发上限峰值正好 5；审计 340 条/秒、p50 3 ms，分段与追加后整链仍通过 `verify-audit`
