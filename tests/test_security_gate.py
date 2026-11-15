"""SLICE-018: the security gate is enforced, not just available."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pre_commit_calls_full_gate():
    text = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "check.py --full" in text
    assert ".venv/Scripts/python.exe" in text


def test_install_hooks_sets_hooks_path(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    hooks = _load("install_hooks", "install_hooks.py")
    assert hooks.install(tmp_path) == 0

    result = subprocess.run(
        ["git", "config", "core.hooksPath"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ".githooks"


def test_pip_audit_ignores_come_from_the_risk_file():
    gate = _load("check", "check.py")
    ids = gate._accepted_vuln_ids()
    text = (ROOT / ".trivyignore.yaml").read_text(encoding="utf-8")
    assert ids
    assert all(cve in text for cve in ids)


def test_sbom_uses_accepted_vuln_ids():
    gate = _load("check", "check.py")
    sbom = _load("sbom", "sbom.py")
    cmd = sbom.build_command("out.json")
    assert all(f"--ignore-vuln={cve}" in cmd for cve in gate._accepted_vuln_ids())


def test_expired_risks_are_not_ignored(tmp_path, monkeypatch):
    entries = (
        "vulnerabilities:\n"
        "  - id: CVE-OLD\n"
        "    statement: old\n"
        "    expired_at: 2020-01-01\n"
        "  - id: CVE-FUTURE\n"
        "    statement: future\n"
        "    expired_at: 2099-01-01\n"
    )
    (tmp_path / ".trivyignore.yaml").write_text(entries, encoding="utf-8")
    for name in ("check", "sbom"):
        module = _load(name, f"{name}.py")
        monkeypatch.setattr(module, "ROOT", tmp_path)
        assert module._accepted_vuln_ids() == ["CVE-FUTURE"]


def test_secrets_scan_uses_baseline():
    text = (ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    assert ".secrets.baseline" in text
    assert (ROOT / ".secrets.baseline").is_file()


def test_secrets_command_does_not_write_baseline():
    gate = _load("check_secrets_cmd", "check.py")
    assert "--baseline" not in gate._secrets_command()


def test_baseline_hits_are_ignored_but_new_hits_fail():
    gate = _load("check_secrets_filter", "check.py")
    # Split the field name so this fixture never reads as a keyword-value pair.
    field = "hashed_" + "secret"
    known = {("docs/evidence/a.txt", "known")}
    results = {
        "docs\\evidence\\a.txt": [{field: "known"}],
        "src/new.py": [{field: "new"}],
    }
    assert gate._new_hits(results, known) == {"src/new.py": 1}


def test_spec_without_threat_model_fails():
    specs = _load("check_specs", "check_specs.py")
    text = "状态: planned\n## 意图\n## 完成判据\n## 反例\n## 证据\n"
    assert "threat-model" in specs.missing_sections(text)


def test_complete_spec_passes():
    specs = _load("check_specs", "check_specs.py")
    text = "状态: planned\n## 意图\n## 完成判据\n## 反例\n## 5 问威胁建模\n## 证据\n"
    assert specs.missing_sections(text) == []


def test_merged_slice_is_grandfathered(tmp_path):
    specs = _load("check_specs", "check_specs.py")
    (tmp_path / "SLICE-999.md").write_text("状态: merged\n## 意图\n", encoding="utf-8")
    assert specs.check_dir(tmp_path) == []


def test_active_slice_is_checked(tmp_path):
    specs = _load("check_specs", "check_specs.py")
    (tmp_path / "SLICE-999.md").write_text("状态: planned\n## 意图\n", encoding="utf-8")
    failures = specs.check_dir(tmp_path)
    assert failures
    assert failures[0][0].name == "SLICE-999.md"


def test_gate_includes_security_steps():
    gate = _load("check_gate_security", "check.py")
    fast = [name for name, _module, _args in gate.FAST_STEPS]
    assert "specs" in fast
    sast = {name: args for name, _module, args in gate.FULL_STEPS}["sast"]
    assert "scripts" in sast
