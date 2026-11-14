"""SLICE-103: Postgres RLS on ADK session tables (ADR-0019)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import urllib.parse

import pytest

from adk_agent.runtime.sessions import build_session_service, session_tenant

DSN = os.environ.get("TEST_POSTGRES_URL")
_HAS_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None
_HAS_ASYNCPG = importlib.util.find_spec("asyncpg") is not None
_live = pytest.mark.skipif(
    not (DSN and _HAS_SQLALCHEMY and _HAS_ASYNCPG),
    reason="TEST_POSTGRES_URL, sqlalchemy and asyncpg are required",
)

APP_ROLE = "adk_session_rls"
OTHER_ROLE = "adk_session_rls_other"
SCHEMA = "test_session_rls"
PASSWORD = "x"
TABLES = ("sessions", "events", "user_states", "app_states")


def test_rls_requires_postgres(tmp_path):
    with pytest.raises(ValueError):
        build_session_service(url="memory://", rls=True)
    with pytest.raises(ValueError):
        build_session_service(sqlite_path=str(tmp_path / "sessions.db"), rls=True)


def _app_dsn(role: str = APP_ROLE) -> str:
    assert DSN is not None
    parts = urllib.parse.urlsplit(DSN)
    netloc = f"{role}:{PASSWORD}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def _prepare() -> None:
    import asyncpg

    assert DSN is not None
    conn = await asyncpg.connect(DSN)
    try:
        for role in (APP_ROLE, OTHER_ROLE):
            exists = await conn.fetchval("select 1 from pg_roles where rolname = $1", role)
            if not exists:
                await conn.execute(
                    f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{PASSWORD}' NOSUPERUSER NOBYPASSRLS"
                )
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await conn.execute(f'CREATE SCHEMA "{SCHEMA}" AUTHORIZATION "{APP_ROLE}"')
        await conn.execute(f'GRANT USAGE ON SCHEMA "{SCHEMA}" TO "{OTHER_ROLE}"')
        await conn.execute(f'ALTER ROLE "{APP_ROLE}" SET search_path = "{SCHEMA}"')
        await conn.execute(f'ALTER ROLE "{OTHER_ROLE}" SET search_path = "{SCHEMA}"')
    finally:
        await conn.close()

    service = build_session_service(url=_app_dsn())
    try:
        await service.create_session(app_name="bootstrap", user_id="bootstrap")
    finally:
        await service.db_engine.dispose()


async def _cleanup() -> None:
    import asyncpg

    assert DSN is not None
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute(f'ALTER ROLE "{APP_ROLE}" RESET search_path')
        await conn.execute(f'ALTER ROLE "{OTHER_ROLE}" RESET search_path')
        await conn.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    finally:
        await conn.close()


@pytest.fixture(scope="module", autouse=True)
def _schema():
    if not (DSN and _HAS_SQLALCHEMY and _HAS_ASYNCPG):
        yield
        return
    asyncio.run(_prepare())
    yield
    asyncio.run(_cleanup())


async def _setup() -> None:
    from adk_agent.runtime.session_rls import engine_for_url, setup_session_rls

    engine = engine_for_url(_app_dsn())
    try:
        await setup_session_rls(engine)
    finally:
        await engine.dispose()


async def _set_enabled(enabled: bool) -> None:
    from sqlalchemy import text

    from adk_agent.runtime.session_rls import engine_for_url

    verb = "ENABLE" if enabled else "DISABLE"
    engine = engine_for_url(_app_dsn())
    try:
        async with engine.begin() as conn:
            for table in TABLES:
                await conn.execute(
                    text(f"ALTER TABLE {table} {verb} ROW LEVEL SECURITY")  # nosec B608
                )
    finally:
        await engine.dispose()


@_live
def test_setup_creates_policies():
    async def scenario() -> set[tuple[str, str]]:
        import asyncpg

        await _setup()
        assert DSN is not None
        conn = await asyncpg.connect(DSN)
        try:
            rows = await conn.fetch(
                "select tablename, policyname from pg_policies where schemaname = $1",
                SCHEMA,
            )
        finally:
            await conn.close()
        return {(row["tablename"], row["policyname"]) for row in rows}

    assert asyncio.run(scenario()) == {(table, f"{table}_tenant") for table in TABLES}


@_live
def test_verify_rls():
    async def scenario() -> bool:
        from adk_agent.runtime.session_rls import (
            SessionRlsUnavailable,
            engine_for_url,
            setup_session_rls,
            verify_session_rls,
        )

        await _set_enabled(False)
        engine = engine_for_url(_app_dsn())
        try:
            try:
                await verify_session_rls(engine)
            except SessionRlsUnavailable:
                failed = True
            else:
                failed = False
            await setup_session_rls(engine)
            await verify_session_rls(engine)
            return failed
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) is True


@_live
def test_cross_tenant_read_returns_none():
    async def scenario():
        await _setup()
        service = build_session_service(url=_app_dsn(), rls=True)
        try:
            with session_tenant("acme"):
                created = await service.create_session(app_name="cross", user_id="acme:alice")
            with session_tenant("other"):
                crossed = await service.get_session(
                    app_name="cross", user_id="acme:alice", session_id=created.id
                )
            with session_tenant("acme"):
                same = await service.get_session(
                    app_name="cross", user_id="acme:alice", session_id=created.id
                )
            return crossed, same
        finally:
            await service.db_engine.dispose()

    crossed, same = asyncio.run(scenario())
    assert crossed is None
    assert same is not None


@_live
def test_missing_tenant_reads_nothing():
    async def scenario():
        await _setup()
        service = build_session_service(url=_app_dsn(), rls=True)
        try:
            with session_tenant("acme"):
                created = await service.create_session(app_name="missing", user_id="acme:alice")
            return await service.get_session(
                app_name="missing", user_id="acme:alice", session_id=created.id
            )
        finally:
            await service.db_engine.dispose()

    assert asyncio.run(scenario()) is None


@_live
def test_unscoped_user_id_is_invisible():
    async def scenario():
        await _setup()
        await _set_enabled(False)
        legacy = build_session_service(url=_app_dsn(), rls=True)
        try:
            created = await legacy.create_session(app_name="legacy", user_id="legacy")
        finally:
            await legacy.db_engine.dispose()
        await _set_enabled(True)
        service = build_session_service(url=_app_dsn(), rls=True)
        try:
            with session_tenant("acme"):
                return await service.get_session(
                    app_name="legacy", user_id="legacy", session_id=created.id
                )
        finally:
            await service.db_engine.dispose()

    assert asyncio.run(scenario()) is None


@_live
def test_enable_rls_is_idempotent():
    async def scenario() -> bool:
        await _setup()
        await _setup()
        return True

    assert asyncio.run(scenario()) is True


@_live
def test_app_name_is_scoped():
    async def scenario() -> str | None:
        import asyncpg

        await _setup()
        service = build_session_service(url=_app_dsn(), rls=True)
        try:
            with session_tenant("acme"):
                created = await service.create_session(app_name="scoped", user_id="acme:alice")
        finally:
            await service.db_engine.dispose()
        assert DSN is not None
        conn = await asyncpg.connect(DSN)
        try:
            return await conn.fetchval(
                f'SELECT app_name FROM "{SCHEMA}".sessions WHERE id = $1', created.id
            )
        finally:
            await conn.close()

    assert asyncio.run(scenario()) == "acme:scoped"


async def _insert_app_state(app_name: str, tenant: str | None = "acme") -> None:
    from sqlalchemy import text

    from adk_agent.runtime.session_rls import engine_for_url

    engine = engine_for_url(_app_dsn())
    try:
        async with engine.begin() as conn:
            if tenant is not None:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tenant, true)"),
                    {"tenant": tenant},
                )
            await conn.execute(
                text(
                    "INSERT INTO app_states (app_name, state, update_time) "
                    "VALUES (:name, CAST('{}' AS json), now()) "
                    "ON CONFLICT (app_name) DO NOTHING"
                ),
                {"name": app_name},
            )
    finally:
        await engine.dispose()


async def _app_state_count(tenant: str, app_name: str) -> int:
    from sqlalchemy import text

    from adk_agent.runtime.session_rls import engine_for_url

    engine = engine_for_url(_app_dsn())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": tenant},
            )
            count = await conn.scalar(
                text("SELECT count(*) FROM app_states WHERE app_name = :name"),
                {"name": app_name},
            )
        return int(count or 0)
    finally:
        await engine.dispose()


@_live
def test_cross_tenant_app_state_is_invisible():
    async def scenario() -> tuple[int, int]:
        await _setup()
        await _insert_app_state("acme:agent")
        return (
            await _app_state_count("acme", "acme:agent"),
            await _app_state_count("other", "acme:agent"),
        )

    acme, other = asyncio.run(scenario())
    assert acme == 1
    assert other == 0


@_live
def test_app_state_write_is_rejected():
    async def scenario() -> bool:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        from adk_agent.runtime.session_rls import engine_for_url

        await _setup()
        engine = engine_for_url(_app_dsn())
        try:
            async with engine.connect() as conn:
                trans = await conn.begin()
                await conn.execute(text("SELECT set_config('app.tenant_id', 'other', true)"))
                try:
                    await conn.execute(
                        text(
                            "INSERT INTO app_states (app_name, state, update_time) "
                            "VALUES ('acme:agent', CAST('{}' AS json), now())"
                        )
                    )
                except DBAPIError:
                    rejected = True
                else:
                    rejected = False
                await trans.rollback()
                return rejected
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) is True


@_live
def test_legacy_app_state_is_invisible():
    async def scenario() -> tuple[int, int]:
        await _setup()
        await _set_enabled(False)
        await _insert_app_state("legacy", tenant=None)
        await _set_enabled(True)
        return (
            await _app_state_count("acme", "legacy"),
            await _app_state_count("other", "legacy"),
        )

    acme, other = asyncio.run(scenario())
    assert acme == 0
    assert other == 0


@_live
def test_enable_rls_requires_table_owner():
    async def scenario() -> bool:
        from sqlalchemy.exc import DBAPIError

        from adk_agent.runtime.session_rls import engine_for_url, setup_session_rls

        await _setup()
        engine = engine_for_url(_app_dsn(OTHER_ROLE))
        try:
            await setup_session_rls(engine)
        except DBAPIError:
            return True
        finally:
            await engine.dispose()
        return False

    assert asyncio.run(scenario()) is True
