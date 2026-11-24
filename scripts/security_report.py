#!/usr/bin/env python3
"""Merge CI scan results into the console security report file."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SecurityReportError(Exception):
    """A scan artifact cannot be read or does not have the expected shape."""


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SecurityReportError(f"{label}: cannot read {path}") from exc
    except (ValueError, RecursionError) as exc:
        raise SecurityReportError(f"{label}: {path} is not usable JSON") from exc


def count_codeql_results(payload: Any) -> int:
    """Count unsuppressed SARIF results across every run."""
    if not isinstance(payload, dict):
        raise SecurityReportError("codeql: SARIF root must be an object")
    runs = payload.get("runs")
    if not isinstance(runs, list):
        raise SecurityReportError("codeql: SARIF has no runs list")
    total = 0
    for run in runs:
        if not isinstance(run, dict):
            raise SecurityReportError("codeql: every run must be an object")
        results = run.get("results", [])
        if not isinstance(results, list):
            raise SecurityReportError("codeql: results must be a list")
        for result in results:
            if not isinstance(result, dict):
                raise SecurityReportError("codeql: every result must be an object")
            suppressions = result.get("suppressions", [])
            if not isinstance(suppressions, list):
                raise SecurityReportError("codeql: suppressions must be a list")
            if not suppressions:
                total += 1
    return total


def count_dependency_vulns(payload: Any) -> int:
    """Count pip-audit vulnerabilities in either JSON layout."""
    entries = payload.get("dependencies") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SecurityReportError("dependencies: expected a list of packages")
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise SecurityReportError("dependencies: every package must be an object")
        vulns = entry.get("vulns", [])
        if not isinstance(vulns, list):
            raise SecurityReportError("dependencies: vulns must be a list")
        total += len(vulns)
    return total


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SecurityReportError(f"{label} must be a non-negative integer")
    return value


def build_report(
    *,
    codeql_open: int,
    vulnerabilities: int,
    notes: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the object described by docs/contracts/security_report.schema.json."""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report: dict[str, Any] = {
        "generated_at": stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "codeql": {"open": _count(codeql_open, "codeql.open")},
        "dependencies": {
            "vulnerabilities": _count(vulnerabilities, "dependencies.vulnerabilities")
        },
    }
    if notes:
        report["notes"] = notes
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codeql-sarif", required=True, help="CodeQL SARIF export")
    parser.add_argument("--pip-audit-json", required=True, help="pip-audit --format json output")
    parser.add_argument("--out", required=True, help="security report written for the console")
    parser.add_argument("--notes", default=None, help="optional note shown with the report")
    args = parser.parse_args(argv)

    try:
        codeql_open = count_codeql_results(_read_json(Path(args.codeql_sarif), "codeql"))
        vulnerabilities = count_dependency_vulns(
            _read_json(Path(args.pip_audit_json), "dependencies")
        )
        report = build_report(
            codeql_open=codeql_open,
            vulnerabilities=vulnerabilities,
            notes=args.notes,
        )
    except SecurityReportError as exc:
        print(f"security_report: {exc}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"wrote {out}: codeql open={report['codeql']['open']}, "
        f"vulnerabilities={report['dependencies']['vulnerabilities']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
