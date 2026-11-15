#!/usr/bin/env python3
"""Writes a CycloneDX SBOM of the installed Python environment."""

from __future__ import annotations

import argparse
import re
import subprocess  # nosec B404  # runs pip-audit
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _accepted_vuln_ids() -> list[str]:
    text = (ROOT / ".trivyignore.yaml").read_text(encoding="utf-8")
    return re.findall(r"^\s*-\s*id:\s*(\S+)", text, flags=re.MULTILINE)


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
