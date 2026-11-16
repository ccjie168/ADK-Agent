"""SLICE-125: the serve-triggers CLI validates its backends before uvicorn."""

from __future__ import annotations

import pytest

from adk_agent import cli


def _keys(tmp_path):
    path = tmp_path / "artifact-keys.json"
    path.write_text('{"k1": "' + "aa" * 32 + '"}', encoding="utf-8")
    return str(path)


def _argv(tmp_path, *extra: str) -> list[str]:
    return [
        "serve-triggers",
        "--triggers-dir",
        str(tmp_path / "triggers"),
        "--registry",
        str(tmp_path / "registry"),
        "--artifact-dir",
        str(tmp_path / "artifacts"),
        "--artifact-keys",
        _keys(tmp_path),
        *extra,
    ]


def test_missing_trigger_store_exits_before_uvicorn(monkeypatch):
    monkeypatch.delenv("TRIGGER_DATABASE_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-triggers",
                "--registry",
                "registry",
                "--artifact-dir",
                "artifacts",
                "--artifact-keys",
                "keys.json",
            ]
        )

    assert exc.value.code == 1


def test_missing_registry_exits_before_uvicorn(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-triggers",
                "--triggers-dir",
                str(tmp_path / "triggers"),
                "--artifact-dir",
                str(tmp_path / "artifacts"),
                "--artifact-keys",
                _keys(tmp_path),
            ]
        )

    assert exc.value.code == 1
    assert "registry" in capsys.readouterr().err.lower()


def test_missing_artifact_store_exits_before_uvicorn(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ARTIFACT_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-triggers",
                "--triggers-dir",
                str(tmp_path / "triggers"),
                "--registry",
                str(tmp_path / "registry"),
                "--artifact-keys",
                _keys(tmp_path),
            ]
        )

    assert exc.value.code == 1
    assert "artifact" in capsys.readouterr().err.lower()


def test_missing_trust_keys_exits_before_uvicorn(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ADK_ARTIFACT_KEYS", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-triggers",
                "--triggers-dir",
                str(tmp_path / "triggers"),
                "--registry",
                str(tmp_path / "registry"),
                "--artifact-dir",
                str(tmp_path / "artifacts"),
            ]
        )

    assert exc.value.code == 1
    assert "trust" in capsys.readouterr().err.lower()


def test_builds_the_service(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(app=app, **kwargs))

    cli.main(_argv(tmp_path, "--host", "127.0.0.1", "--port", "8123"))

    paths = {route.path for route in captured["app"].routes}
    assert "/healthz" in paths
    assert "/v1/tenants/{tenant}/triggers/{trigger_id}/fire" in paths
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123


def test_schedule_tick_below_five_exits_before_uvicorn(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv(tmp_path, "--schedule-tick", "4"))

    assert exc.value.code == 1
    assert "schedule-tick" in capsys.readouterr().err


def test_zero_trigger_attempts_exits_before_uvicorn(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("uvicorn must not run"))

    with pytest.raises(SystemExit) as exc:
        cli.main(_argv(tmp_path, "--trigger-attempts", "0"))

    assert exc.value.code == 1
    assert "trigger-attempts" in capsys.readouterr().err


def test_no_scheduler_parses_then_checks_backends(monkeypatch, capsys):
    monkeypatch.delenv("TRIGGER_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(["serve-triggers", "--no-scheduler"])

    assert exc.value.code == 1
    assert "trigger store" in capsys.readouterr().err.lower()
