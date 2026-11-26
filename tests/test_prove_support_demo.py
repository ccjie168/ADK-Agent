"""SLICE-304: the support demo runs a plan with a human-approved step."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "prove_support_demo.py"


def _run(*extra: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--workdir", str(workdir), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_prove_support_demo_runs(tmp_path):
    proc = _run(workdir=tmp_path)

    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.startswith("PASS ")]
    assert len(lines) >= 6, proc.stdout
    assert any("ticket" in line for line in lines)


def test_prove_support_demo_denied_path(tmp_path):
    proc = _run("--deny", workdir=tmp_path)

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "DENIED" in proc.stdout


def test_prove_support_demo_audits_approval(tmp_path):
    proc = _run(workdir=tmp_path)
    assert proc.returncode == 0, proc.stderr

    audit = tmp_path / "audit.jsonl"
    assert audit.is_file()
    actions = [
        json.loads(line)["event"]["action"]
        for line in audit.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "orchestration.approval" in actions
    assert "orchestration.step" in actions
    assert "orchestration.run" in actions
