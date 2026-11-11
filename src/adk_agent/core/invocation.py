"""The single shape of a data-plane call."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identity import Principal
from .manifest import AgentRef


class Invocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    principal: Principal
    agent_ref: AgentRef
    input: str
    deadline: datetime | None = None
    budget_usd: float | None = Field(default=None, ge=0)

    @field_validator("deadline")
    @classmethod
    def _timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("deadline must be timezone-aware")
        return value
