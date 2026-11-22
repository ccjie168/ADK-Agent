"""Semantic layer contracts (ADR-0038): terminology, capability, data domain, orchestration."""

from __future__ import annotations

from .capability import CapabilityId
from .store import ConceptSchemeStore, ConceptSchemeStoreUnavailable
from .terminology import Concept, ConceptMapping, ConceptScheme, MappingKind, Term

__all__ = [
    "CapabilityId",
    "Concept",
    "ConceptMapping",
    "ConceptScheme",
    "ConceptSchemeStore",
    "ConceptSchemeStoreUnavailable",
    "MappingKind",
    "Term",
]
