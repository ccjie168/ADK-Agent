"""SLICE-048: CLI flags for A2A audit and quota."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli
from adk_agent.audit import JsonlAuditSink
from adk_agent.runtime.quota import InMemoryQuotaManager


def _quota_file(tmp_path) -> str:
    path = tmp_path / "quota.json"
    path.write_text(json.dumps({"tenants": {"local": {"max_runs": 1}}}), encoding="utf-8")
    return str(path)


def _patch_serve(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())
    monkeypatch.setattr("adk_agent.a2a.serve_a2a", lambda agent, **kwargs: captured.update(kwargs))
    return captured


def test_serve_a2a_forwards_audit_and_quota(tmp_path, monkeypatch):
    captured = _patch_serve(monkeypatch)
    monkeypatch.delenv("QUOTA_URL", raising=False)
    audit = str(tmp_path / "audit.jsonl")

    cli.main(
        [
            "serve-a2a",
            "--agent",
            "x.py",
            "--audit-file",
            audit,
            "--quota-config",
            _quota_file(tmp_path),
        ]
    )

    assert isinstance(captured["audit"], JsonlAuditSink)
    assert isinstance(captured["quota"], InMemoryQuotaManager)
    assert captured["quota_config"].tenants["local"].max_runs == 1


def test_bad_quota_config_exits_1(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["serve-a2a", "--agent", "x.py", "--quota-config", str(bad)])

    assert exc.value.code == 1
    assert "quota config" in capsys.readouterr().err


def test_audit_flags_are_exclusive(tmp_path, monkeypatch):
    _patch_serve(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--audit-file",
                str(tmp_path / "audit.jsonl"),
                "--audit-url",
                "http://127.0.0.1:9/v1/events",
            ]
        )

    assert exc.value.code == 2


def test_runtime_flags_default_off(monkeypatch):
    captured = _patch_serve(monkeypatch)

    cli.main(["serve-a2a", "--agent", "x.py"])

    assert captured["audit"] is None
    assert captured["quota"] is None
    assert captured["quota_config"] is None


def _manifest(tmp_path, exposure="a2a") -> str:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "id": "bot",
                "version": "1.0.0",
                "tenant": "acme",
                "owner": "alice",
                "model_policy": {"provider_allowlist": ["litellm"]},
                "exposure": exposure,
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def _token_file(tmp_path) -> str:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"peer-a": "a" * 64}), encoding="utf-8")
    return str(path)


def test_peer_dir_and_db_exclusive(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    monkeypatch.delenv("ADK_MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--manifest",
                _manifest(tmp_path),
                "--peer-dir",
                "d",
                "--peer-db",
                "postgresql://x",
                "--peer-token-file",
                _token_file(tmp_path),
            ]
        )

    assert exc.value.code == 2
    assert "peer-dir" in capsys.readouterr().err


def test_oidc_and_token_exclusive(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    monkeypatch.delenv("ADK_MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--manifest",
                _manifest(tmp_path),
                "--peer-dir",
                str(tmp_path),
                "--peer-token-file",
                _token_file(tmp_path),
                "--oidc-config",
                "oidc.json",
            ]
        )

    assert exc.value.code == 2
    assert "oidc-config" in capsys.readouterr().err


def test_peer_mode_requires_manifest(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    monkeypatch.delenv("ADK_MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--peer-dir",
                str(tmp_path),
                "--peer-token-file",
                _token_file(tmp_path),
            ]
        )

    assert exc.value.code == 2
    assert "manifest" in capsys.readouterr().err


def test_peer_mode_rejects_auth_token(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    monkeypatch.setenv("ADK_MCP_AUTH_TOKEN", "secret")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--manifest",
                _manifest(tmp_path),
                "--peer-dir",
                str(tmp_path),
                "--peer-token-file",
                _token_file(tmp_path),
            ]
        )

    assert exc.value.code == 2


def test_peer_exposure_mismatch(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    monkeypatch.delenv("ADK_MCP_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--manifest",
                _manifest(tmp_path, exposure="mcp"),
                "--peer-dir",
                str(tmp_path),
                "--peer-token-file",
                _token_file(tmp_path),
            ]
        )

    assert exc.value.code == 2
    assert "exposure" in capsys.readouterr().err


def test_peer_mode_forwards_stores(tmp_path, monkeypatch):
    captured = _patch_serve(monkeypatch)
    monkeypatch.delenv("ADK_MCP_AUTH_TOKEN", raising=False)

    cli.main(
        [
            "serve-a2a",
            "--agent",
            "x.py",
            "--manifest",
            _manifest(tmp_path),
            "--peer-dir",
            str(tmp_path),
            "--peer-token-file",
            _token_file(tmp_path),
        ]
    )

    from adk_agent.registry import FilePeerGrantStore, FilePeerStore

    assert isinstance(captured["peers"], FilePeerStore)
    assert isinstance(captured["peer_grants"], FilePeerGrantStore)
    assert captured["peer_tokens"] == {"peer-a": "a" * 64}
    assert captured["manifest"].exposure == "a2a"
    assert captured["oidc"] is None
    assert captured["auth_token"] is None
    assert captured["allow_unauthenticated"] is False
