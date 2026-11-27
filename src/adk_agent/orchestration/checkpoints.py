"""Durable plan checkpoints for resume after a process restart."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..pg import LazyPool, normalize_dsn, require_asyncpg

CheckpointStatus = Literal["running", "waiting_approval", "completed", "cancelled", "failed"]


class CheckpointError(RuntimeError):
    """Base class for checkpoint failures."""


class CheckpointStoreUnavailable(CheckpointError):
    """The checkpoint backend cannot be reached or lacks its driver."""


class CheckpointCorrupt(CheckpointError):
    """The stored checkpoint does not match the plan or cannot be read."""


class CheckpointTerminal(CheckpointError):
    """The run reached a terminal state and must not resume."""


class RunCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: str = Field(min_length=1)
    plan_digest: str = Field(min_length=1)
    status: CheckpointStatus
    outputs: dict[str, str] = Field(default_factory=dict)
    spent_usd: float = Field(default=0.0, ge=0)
    completed_steps: list[str] = Field(default_factory=list)
    waiting_step: str | None = None
    approval_request_id: str | None = None
    final_text: str = ""
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must be timezone aware")
        return value


class CheckpointStore(Protocol):
    async def load(self, tenant: str, run_id: str) -> RunCheckpoint | None: ...

    async def save(self, checkpoint: RunCheckpoint) -> None: ...


class InMemoryCheckpointStore:
    """Process-local store for tests and single-process runs."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], RunCheckpoint] = {}

    async def load(self, tenant: str, run_id: str) -> RunCheckpoint | None:
        return self._items.get((tenant, run_id))

    async def save(self, checkpoint: RunCheckpoint) -> None:
        self._items[(checkpoint.tenant, checkpoint.run_id)] = checkpoint


class PostgresCheckpointStore:
    """Shared checkpoints with tenant RLS, one row per run."""

    def __init__(self, dsn: str) -> None:
        self._pool = LazyPool(
            dsn,
            what="checkpoint",
            unavailable=CheckpointStoreUnavailable,
            setup=self._ensure_schema,
        )

    async def close(self) -> None:
        await self._pool.close()

    async def _ensure_schema(self, pool: Any) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS adk_run_checkpoints ("
                "tenant text NOT NULL, run_id text NOT NULL, plan_id text NOT NULL, "
                "plan_version text NOT NULL, plan_digest text NOT NULL, status text NOT NULL, "
                "outputs text NOT NULL, spent_usd double precision NOT NULL, "
                "completed_steps text NOT NULL, waiting_step text, approval_request_id text, "
                "final_text text NOT NULL, "
                "updated_at timestamptz NOT NULL, PRIMARY KEY (tenant, run_id))"
            )
            await conn.execute(
                "ALTER TABLE adk_run_checkpoints ADD COLUMN IF NOT EXISTS approval_request_id text"
            )
            await conn.execute("ALTER TABLE adk_run_checkpoints ENABLE ROW LEVEL SECURITY")
            await conn.execute("ALTER TABLE adk_run_checkpoints FORCE ROW LEVEL SECURITY")
            await conn.execute(
                "DROP POLICY IF EXISTS adk_run_checkpoints_tenant ON adk_run_checkpoints"
            )
            await conn.execute(
                "CREATE POLICY adk_run_checkpoints_tenant ON adk_run_checkpoints "
                "USING (tenant = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant = current_setting('app.tenant_id', true))"
            )

    async def load(self, tenant: str, run_id: str) -> RunCheckpoint | None:
        pool = await self._pool.get()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
            row = await conn.fetchrow(
                "SELECT tenant, run_id, plan_id, plan_version, plan_digest, status, "
                "outputs, spent_usd, completed_steps, waiting_step, approval_request_id, "
                "final_text, updated_at "
                "FROM adk_run_checkpoints WHERE tenant = $1 AND run_id = $2",
                tenant,
                run_id,
            )
        if row is None:
            return None
        try:
            return RunCheckpoint(
                tenant=row["tenant"],
                run_id=row["run_id"],
                plan_id=row["plan_id"],
                plan_version=row["plan_version"],
                plan_digest=row["plan_digest"],
                status=row["status"],
                outputs=json.loads(row["outputs"]),
                spent_usd=float(row["spent_usd"]),
                completed_steps=json.loads(row["completed_steps"]),
                waiting_step=row["waiting_step"],
                approval_request_id=row["approval_request_id"],
                final_text=row["final_text"],
                updated_at=row["updated_at"],
            )
        except (ValueError, TypeError) as exc:
            raise CheckpointCorrupt("stored checkpoint is not readable") from exc

    async def save(self, checkpoint: RunCheckpoint) -> None:
        pool = await self._pool.get()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", checkpoint.tenant)
            await conn.execute(
                "INSERT INTO adk_run_checkpoints "
                "(tenant, run_id, plan_id, plan_version, plan_digest, status, outputs, "
                "spent_usd, completed_steps, waiting_step, approval_request_id, final_text, "
                "updated_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
                "ON CONFLICT (tenant, run_id) DO UPDATE SET "
                "plan_id = EXCLUDED.plan_id, plan_version = EXCLUDED.plan_version, "
                "plan_digest = EXCLUDED.plan_digest, status = EXCLUDED.status, "
                "outputs = EXCLUDED.outputs, spent_usd = EXCLUDED.spent_usd, "
                "completed_steps = EXCLUDED.completed_steps, "
                "waiting_step = EXCLUDED.waiting_step, "
                "approval_request_id = EXCLUDED.approval_request_id, "
                "final_text = EXCLUDED.final_text, "
                "updated_at = EXCLUDED.updated_at",
                checkpoint.tenant,
                checkpoint.run_id,
                checkpoint.plan_id,
                checkpoint.plan_version,
                checkpoint.plan_digest,
                checkpoint.status,
                json.dumps(checkpoint.outputs, ensure_ascii=False, sort_keys=True),
                checkpoint.spent_usd,
                json.dumps(checkpoint.completed_steps),
                checkpoint.waiting_step,
                checkpoint.approval_request_id,
                checkpoint.final_text,
                checkpoint.updated_at,
            )


def build_checkpoint_store(url: str | None) -> CheckpointStore:
    """Pick the in-memory store for an empty URL, else Postgres."""
    if not url:
        return InMemoryCheckpointStore()
    dsn = normalize_dsn(url, what="checkpoint", unavailable=CheckpointStoreUnavailable)
    require_asyncpg(what="checkpoint", unavailable=CheckpointStoreUnavailable)
    return PostgresCheckpointStore(dsn)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
