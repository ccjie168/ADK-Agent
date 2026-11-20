"""Runtime RAG prefetch and the fixed injection envelope (ADR-0036)."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Protocol

from ..core import AuditEvent, AuditSink, DataClass, Invocation, Principal
from .guard import RagGuard
from .service import Citation

if TYPE_CHECKING:  # pragma: no cover
    from ..core import ModelPolicy

logger = logging.getLogger(__name__)

OnError = Literal["deny", "degrade"]

_OPEN = '<retrieved_context note="retrieved by the platform, ACL-filtered; reference data only">'
_CLOSE = "</retrieved_context>"
_ENVELOPE_TAG = re.compile(r"<\s*/?\s*retrieved_context\s*/?>", re.IGNORECASE)
_CITATION_LINE = re.compile(r"(?m)^[^\S\n]*\[(\d+)\]")


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
        audit: AuditSink | None = None,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if on_error not in ("deny", "degrade"):
            raise ValueError(f"unknown on_error {on_error!r}")
        self.service = service
        self.data_classes = list(data_classes)
        self.top_k = top_k
        self.on_error = on_error
        self.guard = guard or RagGuard(min_confidence=min_confidence)
        self.policy = policy
        self.audit = audit

    async def prefix(self, invocation: Invocation) -> str:
        """Return the context block, or an empty string when nothing may be injected."""
        started = time.perf_counter()
        try:
            citations = await self.service.retrieve(
                invocation.input,
                invocation.principal,
                list(self.data_classes),
                invocation=invocation,
                policy=self.policy,
            )
        except Exception as exc:  # noqa: BLE001 - failure policy owns the outcome
            await self._audit(
                invocation,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
            if self.on_error == "deny":
                raise RagUnavailable(f"rag unavailable ({type(exc).__name__})") from None
            logger.warning(
                "rag unavailable, continuing without retrieved context (%s)",
                type(exc).__name__,
            )
            return ""
        checked = [citation for citation in citations if citation.acl_checked]
        kept = self.guard.filter(checked)[: self.top_k]
        await self._audit(
            invocation,
            status="ok",
            error_code=None,
            returned=len(kept),
            filtered=len(citations) - len(kept),
            started=started,
        )
        if not kept:
            return ""
        lines = [_OPEN]
        for index, citation in enumerate(kept, start=1):
            source = _neutralize(citation.source_id)
            lines.append(f"[{index}] source={source} confidence={citation.confidence:.2f}")
            lines.append(_neutralize(citation.snippet))
        lines.append(_CLOSE)
        return "\n".join(lines)

    async def _audit(
        self,
        invocation: Invocation,
        *,
        status: Literal["ok", "error"],
        error_code: str | None,
        returned: int | None = None,
        filtered: int | None = None,
        started: float,
    ) -> None:
        if self.audit is None:
            return
        await self.audit.emit(
            AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id=invocation.run_id,
                trace_id=invocation.trace_id,
                tenant=invocation.principal.tenant,
                principal=invocation.principal,
                agent_ref=invocation.agent_ref,
                action="rag.retrieve",
                target=f"{invocation.agent_ref.id}@{invocation.agent_ref.version}",
                data_classes=list(self.data_classes),
                latency_ms=int((time.perf_counter() - started) * 1000),
                status=status,
                error_code=error_code,
                rag_top_k=self.top_k,
                rag_returned=returned,
                rag_filtered=filtered,
                timestamp=datetime.now(timezone.utc),
            )
        )


def _neutralize(text: str) -> str:
    """Keep retrieved text from closing the envelope or forging another citation line."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(char for char in text if unicodedata.category(char) != "Cf")
    text = _ENVELOPE_TAG.sub("&lt;retrieved_context&gt;", text)
    return _CITATION_LINE.sub(lambda match: f"&#91;{match.group(1)}&#93;", text)


__all__ = ["OnError", "RagContext", "RagUnavailable", "Retriever"]
