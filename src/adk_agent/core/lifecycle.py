"""Agent lifecycle state and its transitions (ADR-0010)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

LifecycleStatus = Literal["published", "deprecated", "retired"]

_ALLOWED: dict[str, frozenset[str]] = {
    "published": frozenset({"deprecated", "retired"}),
    "deprecated": frozenset({"published", "retired"}),
    "retired": frozenset(),
}


class LifecycleTransitionError(Exception):
    """A lifecycle change is not allowed from the current status."""


class AgentLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: LifecycleStatus
    changed_at: datetime | None = None
    changed_by: str | None = None
    reason: str = ""

    @field_validator("changed_at")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("changed_at must be timezone-aware")
        return value

    @classmethod
    def default(cls) -> AgentLifecycle:
        return cls(status="published")


def transition_lifecycle(
    current: AgentLifecycle,
    target: LifecycleStatus,
    *,
    changed_by: str,
    reason: str = "",
    now: datetime | None = None,
) -> AgentLifecycle:
    """Apply ADR-0010's transition matrix. Setting the current status is a no-op."""
    if target == current.status:
        return current
    if target not in _ALLOWED[current.status]:
        raise LifecycleTransitionError(f"cannot transition from {current.status!r} to {target!r}")
    return AgentLifecycle(
        status=target,
        changed_at=now if now is not None else datetime.now(timezone.utc),
        changed_by=changed_by,
        reason=reason,
    )


__all__ = [
    "AgentLifecycle",
    "LifecycleStatus",
    "LifecycleTransitionError",
    "transition_lifecycle",
]
