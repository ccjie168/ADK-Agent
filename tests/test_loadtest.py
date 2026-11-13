"""SLICE-056: quota and audit load harness."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "loadtest.py"
_SPEC = importlib.util.spec_from_file_location("loadtest", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
loadtest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(loadtest)


def test_percentiles_nearest_rank():
    values = [float(index) for index in range(1, 101)]

    assert loadtest.percentile(values, 50) == 50
    assert loadtest.percentile(values, 95) == 95
    assert loadtest.percentile(values, 99) == 99
    assert loadtest.percentile([], 50) == 0.0


def test_quota_report_shape():
    report = asyncio.run(loadtest.run_quota(requests=10, concurrency=4, max_runs=5))

    assert report["scenario"] == "quota"
    assert report["tenant"].startswith("loadtest-")
    assert report["requests"] == 10
    assert report["concurrency"] == 4
    assert set(report["latency_ms"]) == {"p50", "p95", "p99", "max"}
    assert isinstance(report["throughput_per_s"], float)
    assert report["ok"] + report["denied"] + report["errors"] == 10
    assert report["invariants"]
    assert all(item["holds"] is True for item in report["invariants"])


def test_quota_max_runs_never_oversells():
    report = asyncio.run(
        loadtest.run_quota(requests=50, concurrency=50, max_runs=5),
    )

    assert report["ok"] == 5
    assert report["denied"] == 45
    assert report["errors"] == 0


def test_quota_concurrency_peak():
    report = asyncio.run(
        loadtest.run_quota(
            requests=24,
            concurrency=24,
            max_concurrent=3,
            hold_seconds=0.02,
        ),
    )

    assert report["peak_active"] <= 3
    assert report["denied"] >= 1
    assert report["ok"] + report["denied"] + report["errors"] == 24


def test_quota_requires_a_limit():
    with pytest.raises(loadtest.LoadtestError):
        asyncio.run(loadtest.run_quota(requests=1, concurrency=1))


def test_audit_writes_and_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"

    report = asyncio.run(loadtest.run_audit(records=25, path=path))

    assert report["scenario"] == "audit"
    assert report["ok"] == 25
    assert report["errors"] == 0
    assert report["verify_records"] == 25
    assert all(item["holds"] is True for item in report["invariants"])


def test_audit_with_rotation(tmp_path):
    path = tmp_path / "audit.jsonl"

    report = asyncio.run(loadtest.run_audit(records=25, path=path, max_records=10))

    assert report["verify_records"] == 25
    assert (tmp_path / "audit.jsonl.000001").exists()


def test_audit_refuses_existing_file(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"old":1}\n', encoding="utf-8")

    with pytest.raises(loadtest.LoadtestError):
        asyncio.run(loadtest.run_audit(records=1, path=path))

    assert path.read_text(encoding="utf-8") == '{"old":1}\n'


def test_audit_append_keeps_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    asyncio.run(loadtest.run_audit(records=3, path=path))

    report = asyncio.run(loadtest.run_audit(records=2, path=path, append=True))

    assert report["verify_records"] == 5


def test_records_are_bounded(tmp_path):
    with pytest.raises(loadtest.LoadtestError):
        asyncio.run(
            loadtest.run_audit(records=loadtest.MAX_RECORDS + 1, path=tmp_path / "a.jsonl"),
        )


def test_cli_writes_report(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"

    code = loadtest.main(["audit", "--records", "5", "--path", str(path)])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scenario"] == "audit"
    assert report["verify_records"] == 5


def test_cli_requires_arguments():
    with pytest.raises(SystemExit) as exc:
        loadtest.main(["quota"])

    assert exc.value.code == 2
