"""In-memory structured retrieval with ACL and data_classes filtering (ADR-0032)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..core import DataClass, Invocation, ModelPolicy, Principal
from .guard import RagGuard
from .service import Citation


class RagSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    data_classes: list[DataClass] = Field(default_factory=list)
    allowed_tenants: tuple[str, ...] | None = None
    allowed_subjects: tuple[str, ...] | None = None


class InMemoryRagService:
    """Structured retrieval over an in-memory source list, ACL-filtered."""

    def __init__(self, sources: list[RagSource], guard: RagGuard | None = None) -> None:
        self._sources = list(sources)
        self._guard = guard

    async def retrieve(
        self,
        query: str,
        principal: Principal,
        data_classes: list[DataClass],
        *,
        invocation: Invocation | None = None,
        policy: ModelPolicy | None = None,
    ) -> list[Citation]:
        allowed_classes = set(data_classes)
        results: list[Citation] = []
        for source in self._sources:
            if not self._acl_allows(source, principal):
                continue
            if not set(source.data_classes).issubset(allowed_classes):
                continue
            if query and query.lower() not in source.snippet.lower():
                continue
            results.append(
                Citation(
                    source_id=source.source_id,
                    snippet=source.snippet,
                    acl_checked=True,
                    confidence=1.0,
                )
            )
        if self._guard is not None:
            return self._guard.filter(results)
        return results

    @staticmethod
    def _acl_allows(source: RagSource, principal: Principal) -> bool:
        tenant_ok = source.allowed_tenants is None or principal.tenant in source.allowed_tenants
        subject_ok = source.allowed_subjects is None or principal.subject in source.allowed_subjects
        return tenant_ok and subject_ok


__all__ = ["InMemoryRagService", "RagSource"]
