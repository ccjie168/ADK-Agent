"""SLICE-101: dependency locks and release integrity."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "requirements" / "runtime.lock"
DEV = ROOT / "requirements" / "dev.lock"
DOCKERFILE = ROOT / "Dockerfile"
CI = ROOT / ".github" / "workflows" / "ci.yml"
TRIVY_IGNORES = ROOT / ".trivyignore.yaml"
MANIFESTS = (
    ROOT / "deploy" / "k8s" / "multi-replica.yaml",
    ROOT / "deploy" / "k8s" / "deployment.yaml",
)


def _entries(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _names(entries: list[str]) -> set[str]:
    return {
        re.split(r"[=<>!;\s\[]", entry, maxsplit=1)[0].lower().replace("_", "-")
        for entry in entries
    }


def test_lock_files_are_fully_pinned():
    for path in (RUNTIME, DEV):
        entries = _entries(path)
        assert entries, f"{path.name} is empty"
        for entry in entries:
            assert "==" in entry, f"{path.name}: {entry}"
            assert "--hash=sha256:" in entry, f"{path.name}: {entry}"


def test_lock_files_cover_declared_dependencies():
    runtime = _names(_entries(RUNTIME))
    dev = _names(_entries(DEV))
    for name in (
        "google-adk",
        "anthropic",
        "litellm",
        "uvicorn",
        "pyjwt",
        "cryptography",
        "redis",
    ):
        assert name in runtime, f"{name} missing from runtime.lock"
        assert name in dev, f"{name} missing from dev.lock"
    for name in (
        "pytest",
        "ruff",
        "mypy",
        "pip-audit",
        "detect-secrets",
        "bandit",
        "import-linter",
        "pip-tools",
    ):
        assert name in dev, f"{name} missing from dev.lock"


def test_dockerfile_installs_from_runtime_lock():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "requirements/runtime.lock" in text
    assert "--require-hashes" in text
    assert "--no-deps ." in text
    assert "google-adk[mcp]" not in text
    assert re.search(r"ARG PYTHON_IMAGE=python:3\.13-slim@sha256:[0-9a-f]{64}", text)
    assert "apt-get install" in text
    assert "zlib1g" in text


def test_trivy_ignores_have_expiry():
    blocks = TRIVY_IGNORES.read_text(encoding="utf-8").split("- id:")[1:]
    assert blocks
    for block in blocks:
        assert "statement:" in block
        assert re.search(r"expired_at: \d{4}-\d{2}-\d{2}", block)


def test_ci_uses_locks_builds_and_scans():
    text = CI.read_text(encoding="utf-8")
    assert "requirements/dev.lock" in text
    assert "--require-hashes" in text
    assert "docker build" in text
    assert "trivy" in text.lower()
    assert "sbom.json" in text
    assert "pip install -e" not in text


def test_build_backend_is_locked():
    for path in (RUNTIME, DEV):
        names = _names(_entries(path))
        assert "hatchling" in names, f"{path.name} lacks hatchling"


def test_builds_disable_build_isolation():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"--no-build-isolation\s+--no-deps \.", dockerfile)
    ci = CI.read_text(encoding="utf-8")
    assert re.search(r"--no-build-isolation\s+--no-deps \.", ci)


def test_actions_are_pinned_by_sha():
    lines = [
        line.strip() for line in CI.read_text(encoding="utf-8").splitlines() if "uses:" in line
    ]
    assert lines
    for line in lines:
        ref = line.split("uses:", 1)[1].strip().split()[0]
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), line
        assert re.search(r"#\s*v?\d+\.\d+\.\d+", line), line


def test_manifests_pin_image_digest():
    for path in MANIFESTS:
        text = path.read_text(encoding="utf-8")
        assert "adk-agent:latest" not in text, path.name
        assert re.search(r"image: adk-agent@sha256:[0-9a-f]{64}", text), path.name
