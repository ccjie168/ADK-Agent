#!/usr/bin/env python3
"""Negative verification (S4): inject a defect and prove the gate goes red.

Each gate step must fail for its own reason, then the repo must return green
after the probe is removed. Usage:

    python scripts/negative_check.py
    python scripts/negative_check.py --output docs/evidence/negative-check-YYYYMMDD.txt
"""

from __future__ import annotations

import subprocess  # nosec B404  # runs the gate
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
PROBE = ROOT / "src" / "adk_agent" / "_negative_probe.py"
TEST_PROBE = ROOT / "tests" / "test_negative_probe.py"

# Split so this script never contains a contiguous fake key that the secrets
# gate would flag; the probe file written at runtime does.
_FAKE_KEY = "AKIA" + "IOSFODNN7EXAMPLE"

CASES = [
    ("format", PROBE, "x=1\n"),
    ("lint", PROBE, "import os\n"),
    ("types", PROBE, 'x: int = "s"\n'),
    ("secrets", PROBE, f'AWS_ACCESS_KEY_ID = "{_FAKE_KEY}"\n'),
    ("test", TEST_PROBE, "def test_negative_probe():\n    assert 1 == 2\n"),
]


def _run_gate() -> tuple[int, str]:
    proc = subprocess.run(  # nosec B603  # fixed gate command, no shell
        [PY, "scripts/check.py", "--fast"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    ok = True
    lines: list[str] = []

    for step, path, content in CASES:
        path.write_text(content, encoding="utf-8")
        try:
            _rc, output = _run_gate()
        finally:
            path.unlink(missing_ok=True)

        went_red = f"[FAIL] {step}" in output
        line = f"{step}: injected defect -> {'RED (ok)' if went_red else 'NOT RED (BAD)'}"
        lines.append(line)
        print(line)
        if not went_red:
            ok = False
            print(output)

    _rc, output = _run_gate()
    green = "ALL PASS" in output
    lines.append(f"restore: {'ALL PASS (ok)' if green else 'NOT GREEN (BAD)'}")
    print(lines[-1])
    if not green:
        ok = False
        print(output)

    if "--output" in sys.argv:
        target = Path(sys.argv[sys.argv.index("--output") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {target}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
