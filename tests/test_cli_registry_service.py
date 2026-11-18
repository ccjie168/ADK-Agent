"""SLICE-071: serve-registry builds the control plane from the environment."""

from __future__ import annotations

import pytest

from adk_agent import cli

DSN = "postgresql://adk:adk@127.0.0.1:55432/adk"  # pragma: allowlist secret


def _argv(*extra: str) -> list[str]:
    return ["serve-registry", "--auth-token-env", "REG_TOKEN", *extra]


def test_missing_database_url(monkeypatch, capsys):
    monkeypatch.delenv("REGISTRY_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv())

    assert exc.value.code == 1
    assert "database" in capsys.readouterr().err.lower()


def test_invalid_database_url(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_argv("--database-url", "mysql://localhost/adk"))

    assert exc.value.code == 1
    assert "registry" in capsys.readouterr().err.lower()


def test_builds_service(monkeypatch):
    monkeypatch.setenv("REG_TOKEN", "secret")
    captured: dict = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app, **kwargs))

    cli.main(_argv("--database-url", DSN))

    paths = {route.path for route in captured["app"].routes}
    assert {"/v1/tenants", "/v1/agents", "/v1/agents/{tenant}/{agent_id}/{version}"} <= paths
    assert "/v1/artifacts/{digest}" in paths


def test_builds_eval_store(monkeypatch):
    monkeypatch.setenv("REG_TOKEN", "secret")
    created: list = []

    class FakeEvalStore:
        def __init__(self, url: str) -> None:
            created.append(url)

    monkeypatch.setattr("adk_agent.registry.PostgresEvalReportStore", FakeEvalStore)
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)

    cli.main(_argv("--database-url", DSN))

    assert created == [DSN]


def test_builds_lifecycle_store(monkeypatch):
    monkeypatch.setenv("REG_TOKEN", "secret")
    created: list = []

    class FakeLifecycleStore:
        def __init__(self, url: str) -> None:
            created.append(url)

    monkeypatch.setattr("adk_agent.registry.PostgresAgentLifecycleStore", FakeLifecycleStore)
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)

    cli.main(_argv("--database-url", DSN))

    assert created == [DSN]


def test_artifact_source_exclusive(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("REG_TOKEN", "secret")
    monkeypatch.setenv("ARTIFACT_URL", DSN)

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv("--database-url", DSN, "--artifact-dir", str(tmp_path)))

    assert exc.value.code == 1
    assert "artifact" in capsys.readouterr().err.lower()


def test_builds_credential_routes(monkeypatch):
    monkeypatch.setenv("REG_TOKEN", "secret")
    captured: dict = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app))

    cli.main(_argv("--database-url", DSN, "--credentials-dir", "cred"))

    paths = {route.path for route in captured["app"].routes}
    assert "/v1/credentials" in paths
    assert "/v1/credentials/{credential_id}/disable" in paths


def test_invalid_kek_exits(monkeypatch, capsys):
    monkeypatch.setenv("REG_TOKEN", "secret")
    monkeypatch.setenv("ADK_SECRET_KEKS", "not-json")

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv("--database-url", DSN))

    assert exc.value.code == 1
    assert "ADK_SECRET_KEKS" in capsys.readouterr().err


def test_invalid_credential_db_exits(monkeypatch, capsys):
    monkeypatch.setenv("REG_TOKEN", "secret")

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv("--database-url", DSN, "--credential-db", "sqlite:///x.db"))

    assert exc.value.code == 1
    assert "credential store" in capsys.readouterr().err.lower()
