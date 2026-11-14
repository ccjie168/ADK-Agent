"""SLICE-103: the CLI refuses session RLS without its prerequisites."""

from __future__ import annotations

import argparse

import pytest

from adk_agent import cli


def test_rls_requires_tenant_scope(monkeypatch):
    monkeypatch.setenv("SESSION_URL", "postgresql://u:p@db/adk")
    args = argparse.Namespace(session_rls=True, session_tenant_scope=False)
    with pytest.raises(SystemExit) as exc:
        cli._session_rls(args)
    assert exc.value.code == 1


def test_rls_requires_postgres_session_url(monkeypatch):
    monkeypatch.delenv("SESSION_URL", raising=False)
    args = argparse.Namespace(session_rls=True, session_tenant_scope=True)
    with pytest.raises(SystemExit) as exc:
        cli._session_rls(args)
    assert exc.value.code == 1


def test_rls_off_by_default():
    assert cli._session_rls(argparse.Namespace(session_rls=False)) is False


def test_sessions_enable_rls_requires_url(monkeypatch):
    monkeypatch.delenv("SESSION_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["sessions", "enable-rls"])
    assert exc.value.code == 1


def test_sessions_enable_rls_rejects_non_postgres(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["sessions", "enable-rls", "--database-url", "sqlite:///demo.db"])
    assert exc.value.code == 1
    assert "requires a Postgres URL" in capsys.readouterr().err


def test_serve_rejects_rls_without_scope(monkeypatch):
    monkeypatch.setenv("SESSION_URL", "postgresql://u:p@db/adk")
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--agent", "missing.py", "--session-rls", "--transport", "stdio"])
    assert exc.value.code == 1
