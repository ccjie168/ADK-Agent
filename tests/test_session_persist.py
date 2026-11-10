"""SLICE-003: persistent sessions for private deployment."""

from __future__ import annotations

import asyncio

from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from adk_agent.factory import build_runner


def _agent() -> LlmAgent:
    return LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")


def test_build_runner(tmp_path):
    assert build_runner(_agent(), None) is None

    db_path = tmp_path / "nested" / "sessions.db"
    runner = build_runner(_agent(), str(db_path))
    assert type(runner.session_service).__name__ == "SqliteSessionService"
    assert db_path.parent.is_dir()


def test_sqlite_session_survives_restart(tmp_path):
    path = str(tmp_path / "sessions.db")

    async def scenario():
        first = SqliteSessionService(path)
        session = await first.create_session(app_name="a", user_id="u")
        await first.close()
        second = SqliteSessionService(path)
        restored = await second.get_session(app_name="a", user_id="u", session_id=session.id)
        await second.close()
        return restored

    restored = asyncio.run(scenario())
    assert restored is not None
    assert restored.id


def test_in_memory_session_lost_on_restart():
    async def scenario():
        first = InMemorySessionService()
        session = await first.create_session(app_name="a", user_id="u")
        second = InMemorySessionService()
        return await second.get_session(app_name="a", user_id="u", session_id=session.id)

    assert asyncio.run(scenario()) is None
