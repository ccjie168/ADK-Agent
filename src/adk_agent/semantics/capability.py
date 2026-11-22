"""Capability identifiers and their binding to concepts and tools (ADR-0038, layer 2)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

CapabilityId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")]


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: CapabilityId
    concept_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)


def validate_capability_bindings(
    bindings: Sequence[CapabilityBinding],
    *,
    concept_ids: Collection[str],
    tool_ids: Collection[str],
) -> None:
    """Reject duplicate capability ids or references to missing concepts/tools."""
    seen: set[str] = set()
    for binding in bindings:
        if binding.capability_id in seen:
            raise ValueError(f"duplicate capability id {binding.capability_id!r}")
        seen.add(binding.capability_id)
        if binding.concept_id not in concept_ids:
            raise ValueError(
                f"capability {binding.capability_id!r} references missing concept "
                f"{binding.concept_id!r}"
            )
        if binding.tool_id not in tool_ids:
            raise ValueError(
                f"capability {binding.capability_id!r} references missing tool {binding.tool_id!r}"
            )


__all__ = ["CapabilityBinding", "CapabilityId", "validate_capability_bindings"]
