"""SLICE-044: console quota config wiring."""

from __future__ import annotations

import json

import pytest

import adk_agent.console as console_module
import adk_agent.runtime.quota_postgres as quota_postgres
from adk_agent import cli
from adk_agent.runtime.quota import InMemoryQuotaManager


def _agents_file(tmp_path):
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return path


def _config_file(tmp_path) -> str:
    path = tmp_path / "quota.json"
    path.write_text(
        json.dumps({"tenants": {"acme": {"max_runs": 1, "window_seconds": 60}}}),
        encoding="utf-8",
    )
    return str(path)


def _console_args(tmp_path, *extra: str) -> list[str]:
    return ["console", "--agents", str(_agents_file(tmp_path)), *extra]


def test_quota_config_missing_file(tmp_path, monkeypatch, capsys):
    calls: list[dict] = []
    monkeypatch.setattr(console_module, "run_console", lambda *a, **k: calls.append(k))

    with pytest.raises(SystemExit) as exc:
        cli.main(_console_args(tmp_path, "--quota-config", str(tmp_path / "missing.json")))

    assert exc.value.code == 1
    assert "quota config" in capsys.readouterr().err
    assert calls == []


def test_quota_config_invalid_json(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(_console_args(tmp_path, "--quota-config", str(bad)))

    assert exc.value.code == 1
    assert "quota config" in capsys.readouterr().err


def test_console_wires_quota(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(console_module, "run_console", lambda *a, **k: captured.update(k))
    monkeypatch.delenv("QUOTA_URL", raising=False)

    cli.main(_console_args(tmp_path, "--quota-config", _config_file(tmp_path)))

    assert captured["quota_config"].tenants["acme"].max_runs == 1
    assert isinstance(captured["quota"], InMemoryQuotaManager)


def test_quota_url_without_driver_exits_1(tmp_path, monkeypatch, capsys):
    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(quota_postgres, "_import_module", missing)
    monkeypatch.setenv("QUOTA_URL", "postgresql://u:p@localhost:5432/db")

    with pytest.raises(SystemExit) as exc:
        cli.main(_console_args(tmp_path, "--quota-config", _config_file(tmp_path)))

    assert exc.value.code == 1
    assert "asyncpg" in capsys.readouterr().err
