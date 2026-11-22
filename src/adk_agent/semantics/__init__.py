"""Semantic layer contracts (ADR-0038): terminology, capability, data domain, orchestration."""

from __future__ import annotations

from .capability import CapabilityBinding, CapabilityId, validate_capability_bindings
from .domain import DataDomain
from .store import ConceptSchemeStore, ConceptSchemeStoreUnavailable
from .terminology import Concept, ConceptMapping, ConceptScheme, MappingKind, Term

__all__ = [
    "CapabilityBinding",
    "CapabilityId",
    "Concept",
    "ConceptMapping",
    "ConceptScheme",
    "ConceptSchemeStore",
    "ConceptSchemeStoreUnavailable",
    "DataDomain",
    "MappingKind",
    "Term",
    "validate_capability_bindings",
]
