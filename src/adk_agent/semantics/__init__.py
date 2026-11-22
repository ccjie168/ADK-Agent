"""Semantic layer contracts (ADR-0038): terminology, capability, data domain, orchestration."""

from __future__ import annotations

from .capability import CapabilityBinding, CapabilityId, validate_capability_bindings
from .domain import DataDomain
from .routing import RoutedCapability, route_request
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
    "RoutedCapability",
    "Term",
    "route_request",
    "validate_capability_bindings",
]
