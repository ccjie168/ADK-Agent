"""Data ontology layer: domain annotations orthogonal to sensitivity (ADR-0038, layer 3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..core import DataClass


class DataDomain(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    concept_id: str = Field(min_length=1)
    sensitivity: DataClass = Field(default="internal")


__all__ = ["DataDomain"]
