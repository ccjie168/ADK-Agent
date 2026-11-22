"""Concept scheme storage port (ADR-0038, terminology layer)."""

from __future__ import annotations

from typing import Protocol

from .terminology import ConceptScheme


class ConceptSchemeStoreUnavailable(Exception):
    """The terminology store cannot be reached or written."""


class ConceptSchemeStore(Protocol):
    async def put(self, tenant: str, scheme: ConceptScheme) -> ConceptScheme: ...
    async def get(self, tenant: str, scheme_id: str) -> ConceptScheme | None: ...
    async def list(self, tenant: str) -> list[ConceptScheme]: ...


__all__ = ["ConceptSchemeStore", "ConceptSchemeStoreUnavailable"]
