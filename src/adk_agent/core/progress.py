"""Progress events a running agent emits for live UI."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProgressKind = Literal[
    "run.started",
    "tool.call",
    "tool.result",
    "model.text",
    "run.finished",
    "run.failed",
]


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProgressKind
    run_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    author: str | None = None
    tool: str | None = None
    text: str | None = None
    detail: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value
