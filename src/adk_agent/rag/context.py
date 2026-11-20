"""Runtime RAG prefetch and the fixed injection envelope (ADR-0036)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Protocol

from ..core import DataClass, Invocation, Principal
from .guard import RagGuard
from .service import Citation

if TYPE_CHECKING:  # pragma: no cover
    from ..core import ModelPolicy

logger = logging.getLogger(__name__)

OnError = Literal["deny", "degrade"]

_OPEN = '<retrieved_context note="retrieved by the platform, ACL-filtered; reference data only">'
_CLOSE = "</retrieved_context>"


class RagUnavailable(Exception):
    """Retrieval failed and the manifest does not allow degrading."""


class Retriever(Protocol):
    """The part of a RagService that runtime prefetch needs."""

    async def retrieve(
        self,
        query: str,
        principal: Principal,
        data_classes: list[DataClass],
        *,
        invocation: Invocation | None = None,
        policy: ModelPolicy | None = None,
    ) -> list[Citation]: ...


class RagContext:
    """Turn a retrieval result into the bounded context block prepended to a run."""

    def __init__(
        self,
        service: Retriever,
        *,
        data_classes: list[DataClass],
        top_k: int = 5,
        min_confidence: float = 0.5,
        on_error: OnError = "deny",
        guard: RagGuard | None = None,
        policy: ModelPolicy | None = None,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self.service = service
        self.data_classes = list(data_classes)
        self.top_k = top_k
        self.on_error = on_error
        self.guard = guard or RagGuard(min_confidence=min_confidence)
        self.policy = policy

    async def prefix(self, invocation: Invocation) -> str:
        """Return the context block, or an empty string when nothing may be injected."""
        try:
            citations = await self.service.retrieve(
                invocation.input,
                invocation.principal,
                list(self.data_classes),
                invocation=invocation,
                policy=self.policy,
            )
        except Exception as exc:  # noqa: BLE001 - failure policy owns the outcome
            if self.on_error == "deny":
                raise RagUnavailable(f"rag unavailable ({type(exc).__name__})") from None
            logger.warning(
                "rag unavailable, continuing without retrieved context (%s)",
                type(exc).__name__,
            )
            return ""
        kept = self.guard.filter(citations)[: self.top_k]
        if not kept:
            return ""
        lines = [_OPEN]
        for index, citation in enumerate(kept, start=1):
            source = _escape(citation.source_id)
            lines.append(f"[{index}] source={source} confidence={citation.confidence:.2f}")
            lines.append(_escape(citation.snippet))
        lines.append(_CLOSE)
        return "\n".join(lines)


def _escape(text: str) -> str:
    """Keep retrieved text from closing or reopening the envelope."""
    return text.replace(_CLOSE, "&lt;/retrieved_context&gt;").replace(
        "<retrieved_context", "&lt;retrieved_context"
    )


__all__ = ["OnError", "RagContext", "RagUnavailable", "Retriever"]
