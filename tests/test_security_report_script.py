"""SLICE-274: the CI scan summary script behind --security-report."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "security_report.py"
_SPEC = importlib.util.spec_from_file_location("security_report", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
security_report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(security_report)


def test_codeql_counts_unsuppressed_results():
    payload = {
        "runs": [
            {
                "results": [
                    {"ruleId": "py/sql-injection"},
                    {"ruleId": "py/log-injection", "suppressions": [{"kind": "external"}]},
                ]
            },
            {"results": [{"ruleId": "py/path-injection"}]},
        ]
    }

    assert security_report.count_codeql_results(payload) == 2


def test_codeql_rejects_a_non_sarif_document():
    try:
        security_report.count_codeql_results({"results": []})
    except security_report.SecurityReportError as exc:
        assert "runs" in str(exc)
    else:  # pragma: no cover - the error path is the point
        raise AssertionError("missing runs should fail")


def test_dependencies_accept_both_pip_audit_layouts():
    legacy = [
        {"name": "a", "vulns": [{"id": "CVE-1"}]},
        {"name": "b", "vulns": []},
    ]
    current = {"dependencies": legacy, "fixes": []}

    assert security_report.count_dependency_vulns(legacy) == 1
    assert security_report.count_dependency_vulns(current) == 1


def test_build_report_matches_the_contract():
    report = security_report.build_report(
        codeql_open=0,
        vulnerabilities=2,
        notes="nightly",
        now=datetime(2026, 11, 25, tzinfo=timezone.utc),
    )

    assert report == {
        "generated_at": "2026-11-25T00:00:00Z",
        "codeql": {"open": 0},
        "dependencies": {"vulnerabilities": 2},
        "notes": "nightly",
    }


def test_build_report_rejects_negative_and_boolean_counts():
    for value in (-1, True):
        try:
            security_report.build_report(codeql_open=value, vulnerabilities=0)
        except security_report.SecurityReportError:
            continue
        raise AssertionError(f"{value!r} should be rejected")


def test_main_writes_the_report(tmp_path):
    sarif = tmp_path / "codeql.sarif"
    sarif.write_text(json.dumps({"runs": [{"results": [{"ruleId": "x"}]}]}), encoding="utf-8")
    audit = tmp_path / "pip-audit.json"
    audit.write_text(
        json.dumps({"dependencies": [{"name": "pkg", "vulns": [{}, {}]}]}),
        encoding="utf-8",
    )
    out = tmp_path / "scan.json"

    code = security_report.main(
        [
            "--codeql-sarif",
            str(sarif),
            "--pip-audit-json",
            str(audit),
            "--out",
            str(out),
        ]
    )

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["codeql"] == {"open": 1}
    assert report["dependencies"] == {"vulnerabilities": 2}
    assert report["generated_at"].endswith("Z")


def test_main_returns_2_for_a_missing_artifact(tmp_path):
    code = security_report.main(
        [
            "--codeql-sarif",
            str(tmp_path / "missing.sarif"),
            "--pip-audit-json",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path / "scan.json"),
        ]
    )

    assert code == 2
    assert not (tmp_path / "scan.json").exists()


def test_main_returns_2_for_unusable_json(tmp_path):
    sarif = tmp_path / "codeql.sarif"
    sarif.write_text("[" * 200000 + "]" * 200000, encoding="utf-8")
    audit = tmp_path / "pip-audit.json"
    audit.write_text("[]", encoding="utf-8")
    out = tmp_path / "scan.json"

    code = security_report.main(
        ["--codeql-sarif", str(sarif), "--pip-audit-json", str(audit), "--out", str(out)]
    )

    assert code == 2
    assert not out.exists()
