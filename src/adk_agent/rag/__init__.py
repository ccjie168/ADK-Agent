"""RAG service port and structured retrieval (ADR-0032)."""

from __future__ import annotations

from .context import RagContext, RagUnavailable
from .guard import RagGuard, detect_prompt_injection
from .memory import InMemoryRagService, RagSource
from .pgvector_service import PgVectorRagService
from .service import Citation, RagService

__all__ = [
    "Citation",
    "InMemoryRagService",
    "PgVectorRagService",
    "RagContext",
    "RagUnavailable",
    "RagGuard",
    "RagService",
    "RagSource",
    "detect_prompt_injection",
]
