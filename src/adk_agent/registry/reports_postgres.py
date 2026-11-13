"""Postgres-backed eval reports shared across replicas (ADR-0009)."""

from __future__ import annotations

from typing import Any

from ..core import EvalReport
from ..pg import LazyPool, normalize_dsn
from .file import RegistryError, RegistryIntegrityError
from .postgres import RegistryStoreUnavailable
from .reports import EvalReportConflict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_eval_reports (
    tenant text NOT NULL,
    agent_id text NOT NULL,
    version text NOT NULL,
    report jsonb NOT NULL,
    stored_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, agent_id, version)
)
"""

_SELECT_REPORT = (
    "SELECT report FROM adk_eval_reports WHERE tenant = $1 AND agent_id = $2 AND version = $3"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresEvalReportStore:
    """One immutable eval report per published version, in ``adk_eval_reports``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="eval reports", unavailable=RegistryStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="eval reports",
            unavailable=RegistryStoreUnavailable,
            setup=_ensure_schema,
        )

    async def put(self, tenant: str, agent_id: str, version: str, report: EvalReport) -> EvalReport:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_eval_reports (tenant, agent_id, version, report) "
                    "VALUES ($1, $2, $3, $4::jsonb) "
                    "ON CONFLICT (tenant, agent_id, version) DO NOTHING",
                    tenant,
                    agent_id,
                    version,
                    report.model_dump_json(),
                )
                stored = await conn.fetchval(_SELECT_REPORT, tenant, agent_id, version)
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(
                f"eval report write failed ({type(exc).__name__})"
            ) from exc
        label = f"{tenant}/{agent_id}@{version}"
        existing = self._parse(stored, label)
        if existing.model_dump(mode="json") != report.model_dump(mode="json"):
            raise EvalReportConflict(f"{label} already has a different eval report")
        return existing

    async def get(self, tenant: str, agent_id: str, version: str) -> EvalReport | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT_REPORT, tenant, agent_id, version)
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(
                f"eval report read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, f"{tenant}/{agent_id}@{version}")

    async def has(self, tenant: str, agent_id: str, version: str) -> bool:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                found = await conn.fetchval(
                    "SELECT 1 FROM adk_eval_reports "
                    "WHERE tenant = $1 AND agent_id = $2 AND version = $3",
                    tenant,
                    agent_id,
                    version,
                )
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(
                f"eval report read failed ({type(exc).__name__})"
            ) from exc
        return found is not None

    def _parse(self, raw: str | None, label: str) -> EvalReport:
        if raw is None:
            raise RegistryIntegrityError(f"{label}: eval report disappeared during write")
        try:
            return EvalReport.model_validate_json(raw)
        except ValueError as exc:
            raise RegistryIntegrityError(f"{label}: invalid eval report record") from exc


__all__ = ["PostgresEvalReportStore"]
