"""SLICE-009: ports and the dependency rule."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CLI = (
    "from importlinter.cli import lint_imports_command; "
    "lint_imports_command.main(args=['--no-cache'])"
)


def _lint(cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CLI],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def test_ports_defined():
    from adk_agent.core.ports import (
        AgentRegistry,
        AuditSink,
        IdentityProvider,
        PolicyEngine,
        SecretProvider,
        TemplateSource,
    )

    expected = {
        AgentRegistry: {"get", "publish"},
        AuditSink: {"emit"},
        IdentityProvider: {"resolve"},
        PolicyEngine: {"decide"},
        SecretProvider: {"resolve"},
        TemplateSource: {"render"},
    }
    for port, methods in expected.items():
        assert methods <= set(dir(port))


def test_core_isolation():
    result = _lint(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_contract_catches_violation(tmp_path: Path):
    pkg = tmp_path / "badpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("from badpkg import adapter\n")
    (pkg / "adapter.py").write_text("VALUE = 1\n")
    (tmp_path / ".importlinter").write_text(
        textwrap.dedent(
            """
            [importlinter]
            root_package = badpkg
            include_external_packages = False

            [importlinter:contract:isolation]
            name = badpkg.core must not import adapter
            type = forbidden
            source_modules =
                badpkg.core
            forbidden_modules =
                badpkg.adapter
            """
        )
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = _lint(tmp_path, env)
    assert result.returncode != 0
    assert "badpkg.core" in (result.stdout + result.stderr)
