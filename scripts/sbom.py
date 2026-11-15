#!/usr/bin/env python3
"""Writes a CycloneDX SBOM of the installed Python environment."""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404  # runs pip-audit
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _accepted_vuln_ids() -> list[str]:
    """Accepted IDs from .trivyignore.yaml that have not expired."""
    text = (ROOT / ".trivyignore.yaml").read_text(encoding="utf-8")
    accepted: list[str] = []
    for block in text.split("- id:")[1:]:
        vuln = block.split()[0].strip()
        expiry = re.search(r"expired_at:\s*(\d{4}-\d{2}-\d{2})", block)
        if expiry is None or date.fromisoformat(expiry.group(1)) >= date.today():
            accepted.append(vuln)
    return accepted


def build_command(out: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pip_audit",
        "-f",
        "cyclonedx-json",
        "-o",
        out,
        "--progress-spinner",
        "off",
        *[f"--ignore-vuln={vuln}" for vuln in _accepted_vuln_ids()],
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a CycloneDX SBOM.")
    parser.add_argument("-o", "--output", default="sbom.json", help="output path")
    args = parser.parse_args(argv)

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    code = subprocess.run(build_command(str(out_path)), cwd=ROOT).returncode  # nosec B603
    print(f"SBOM: {out_path.resolve()}")
    print(f"Exit code: {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
