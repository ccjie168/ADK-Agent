"""RAG service port and citation type (ADR-0032)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ..core import DataClass, Principal


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    acl_checked: bool = False
    confidence: float = Field(ge=0.0, le=1.0)


class RagService(Protocol):
    async def retrieve(
        self, query: str, principal: Principal, data_classes: list[DataClass]
    ) -> list[Citation]: ...


__all__ = ["Citation", "RagService"]
