"""Deterministic semantic routing (ADR-0038, orchestration layer)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from .capability import CapabilityBinding, CapabilityId
from .terminology import ConceptScheme


class RoutedCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: CapabilityId
    concept_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    matched_label: str = Field(min_length=1)


def route_request(
    text: str,
    scheme: ConceptScheme,
    bindings: Sequence[CapabilityBinding],
) -> list[RoutedCapability]:
    """Return capabilities whose concept labels appear in the request, in concept order."""
    lowered = text.lower()
    by_concept: dict[str, list[CapabilityBinding]] = defaultdict(list)
    for binding in bindings:
        by_concept[binding.concept_id].append(binding)

    routed: list[RoutedCapability] = []
    for concept in scheme.concepts:
        matched = next(
            (
                label.value
                for label in (*concept.pref_labels, *concept.alt_labels, *concept.hidden_labels)
                if label.value.lower() in lowered
            ),
            None,
        )
        if matched is None:
            continue
        for binding in by_concept.get(concept.concept_id, []):
            routed.append(
                RoutedCapability(
                    capability_id=binding.capability_id,
                    concept_id=concept.concept_id,
                    tool_id=binding.tool_id,
                    matched_label=matched,
                )
            )
    return routed


__all__ = ["RoutedCapability", "route_request"]
