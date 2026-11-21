"""Model alias routing: pick the ordered candidates a request may use (ADR-0033)."""

from __future__ import annotations

from ..core import DataClass, ModelCandidate, ModelPolicy
from .gateway import ModelDenied


def resolve_candidates(
    policy: ModelPolicy, alias: str, data_classes: list[DataClass]
) -> list[ModelCandidate]:
    """Return the alias's candidates in order, restricted to those this request may use.

    A candidate is usable when its provider is in the policy allowlist and it admits
    every requested data class (an empty ``allowed_data_classes`` admits all).
    """
    definition = next((entry for entry in policy.model_aliases if entry.alias == alias), None)
    if definition is None:
        raise ModelDenied(f"alias {alias!r} is not defined")
    requested = set(data_classes)
    permitted = [
        candidate
        for candidate in definition.candidates
        if candidate.provider in policy.provider_allowlist
        and (not policy.model_allowlist or candidate.model in policy.model_allowlist)
        and (not candidate.allowed_data_classes or requested <= set(candidate.allowed_data_classes))
    ]
    if not permitted:
        raise ModelDenied(f"alias {alias!r} has no permitted candidate")
    return permitted


__all__ = ["resolve_candidates"]
