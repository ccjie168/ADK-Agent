"""SLICE-034: shared session stores for horizontally scaled workers."""

from __future__ import annotations

import asyncio
import os

import pytest
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.sqlite_session_service import SqliteSessionService

import adk_agent.runtime.sessions as sessions_module
from adk_agent.runtime.sessions import (
    SessionStoreUnavailable,
    build_session_service,
    configured_session_service,
)

_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")


def _missing_import(name: str) -> None:
    raise ImportError(name)


def test_default_is_memory():
    assert isinstance(build_session_service(), InMemorySessionService)


def test_memory_scheme():
    assert isinstance(build_session_service(url="memory://"), InMemorySessionService)


def test_sqlite_path(tmp_path):
    service = build_session_service(sqlite_path=str(tmp_path / "sessions.db"))
    assert isinstance(service, SqliteSessionService)


def test_invalid_url_rejected():
    for url in ("sqlite:///tmp/demo.db", "mysql://db/adk", "postgres://db/adk"):
        with pytest.raises(ValueError):
            build_session_service(url=url)


def test_missing_driver_hint(monkeypatch):
    monkeypatch.setattr(sessions_module, "_import_module", _missing_import)
    with pytest.raises(SessionStoreUnavailable) as exc:
        build_session_service(url="postgresql+asyncpg://u:p@db:5432/adk")
    assert "asyncpg" in str(exc.value)


def test_url_wins_over_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_URL", "memory://")
    service = configured_session_service(str(tmp_path / "demo.db"))
    assert isinstance(service, InMemorySessionService)


def test_no_external_store_returns_none(monkeypatch):
    monkeypatch.delenv("SESSION_URL", raising=False)
    assert configured_session_service(None) is None


@pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
def test_two_workers_share_a_session():
    async def scenario() -> None:
        worker_a = build_session_service(url=_LIVE_URL)
        worker_b = build_session_service(url=_LIVE_URL)
        created = await worker_a.create_session(app_name="workers", user_id="u1")

        found = await worker_b.get_session(app_name="workers", user_id="u1", session_id=created.id)

        assert found is not None
        assert found.id == created.id

    asyncio.run(scenario())
