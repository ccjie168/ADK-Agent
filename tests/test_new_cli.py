"""SLICE-015: the new command writes a template project."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli
from adk_agent.core import AgentManifest


def test_new_creates_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main(["new", "support-bot"])

    project = tmp_path / "support-bot"
    assert (project / "agent.py").is_file()
    assert (project / "manifest.json").is_file()
    assert (project / "README.md").is_file()
    assert (project / "tests" / "test_agent.py").is_file()
    manifest = AgentManifest.model_validate(json.loads((project / "manifest.json").read_text()))
    assert manifest.id == "support-bot"
    assert manifest.tenant == "local"
    assert "created" in capsys.readouterr().out


def test_new_uses_requested_tenant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cli.main(["new", "support-bot", "--tenant", "acme"])

    project = tmp_path / "support-bot"
    manifest = AgentManifest.model_validate(json.loads((project / "manifest.json").read_text()))
    assert manifest.tenant == "acme"


def test_new_rejects_unsafe_tenant(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["new", "support-bot", "--tenant", "../evil"])
    assert exc.value.code == 1
    assert not (tmp_path / "support-bot").exists()


def test_new_refuses_existing_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "support-bot"
    project.mkdir()
    (project / "agent.py").write_text("")

    with pytest.raises(SystemExit) as exc:
        cli.main(["new", "support-bot"])
    assert exc.value.code == 1


def test_new_rejects_unsafe_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["new", "../evil"])
    assert exc.value.code == 1
    assert not (tmp_path.parent / "evil").exists()


def test_new_rejects_unknown_template(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["new", "support-bot", "--template", "nope"])
    assert exc.value.code == 1
