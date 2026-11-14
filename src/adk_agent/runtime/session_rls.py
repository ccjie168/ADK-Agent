"""Postgres row-level security for ADK's session tables (ADR-0019)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .sessions import current_session_tenant

SESSION_TABLES = ("sessions", "events", "user_states", "app_states")


def _tenant_match(table: str) -> str:
    column = "app_name" if table == "app_states" else "user_id"
    return f"split_part({column}, ':', 1) = current_setting('app.tenant_id', true)"


class SessionRlsUnavailable(RuntimeError):
    """The session tables do not carry the RLS policy this process requires."""


def async_session_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


def engine_for_url(url: str) -> AsyncEngine:
    return create_async_engine(async_session_url(url))


def install_session_rls(engine: AsyncEngine) -> None:
    """Set ``app.tenant_id`` at the start of every transaction on ``engine``."""

    def _set_tenant(conn: Any) -> None:
        tenant = current_session_tenant()
        if tenant:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": tenant},
            )

    event.listen(engine.sync_engine, "begin", _set_tenant)


async def setup_session_rls(engine: AsyncEngine) -> None:
    """Create the policies. The calling role must own the session tables."""
    async with engine.begin() as conn:
        missing = [
            table
            for table in SESSION_TABLES
            if await conn.scalar(text("SELECT to_regclass(:name)"), {"name": table}) is None
        ]
        if missing:
            raise SessionRlsUnavailable(
                "session tables are missing: "
                + ", ".join(missing)
                + "; create a session before enabling RLS"
            )
        for table in SESSION_TABLES:
            match = _tenant_match(table)
            # Table names come from the fixed tuple above, never from input.
            await conn.execute(
                text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # nosec B608
            )
            await conn.execute(
                text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # nosec B608
            )
            await conn.execute(
                text(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")  # nosec B608
            )
            await conn.execute(
                text(
                    f"CREATE POLICY {table}_tenant ON {table} "  # nosec B608
                    f"USING ({match}) WITH CHECK ({match})"
                )
            )


async def verify_session_rls(engine: AsyncEngine) -> None:
    """Raise when a session table exists without the forced tenant policy."""
    async with engine.connect() as conn:
        for table in SESSION_TABLES:
            row = (
                await conn.execute(
                    text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity "
                        "FROM pg_class c WHERE c.oid = to_regclass(:name)"
                    ),
                    {"name": table},
                )
            ).one_or_none()
            if row is None:
                raise SessionRlsUnavailable(
                    f"session table {table} is missing; create a session first"
                )
            if not row[0] or not row[1]:
                raise SessionRlsUnavailable(
                    f"session table {table} does not enforce RLS; "
                    "run `adk-agent sessions enable-rls`"
                )
            found = await conn.scalar(
                text(
                    "SELECT 1 FROM pg_policies p "
                    "JOIN pg_class c ON c.relname = p.tablename "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "AND n.nspname = p.schemaname "
                    "WHERE c.oid = to_regclass(:name) AND p.policyname = :policy"
                ),
                {"name": table, "policy": f"{table}_tenant"},
            )
            if found is None:
                raise SessionRlsUnavailable(
                    f"session table {table} lacks the tenant policy; "
                    "run `adk-agent sessions enable-rls`"
                )


__all__ = [
    "SESSION_TABLES",
    "SessionRlsUnavailable",
    "async_session_url",
    "engine_for_url",
    "install_session_rls",
    "setup_session_rls",
    "verify_session_rls",
]
