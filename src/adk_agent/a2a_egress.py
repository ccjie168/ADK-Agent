"""Audit outbound A2A consumer calls at the HTTP transport boundary."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from .audit.hashing import hash_text
from .core import AgentRef, AuditEvent, AuditSink, Principal
from .core.context import current_invocation
from .observability import a2a_span

logger = logging.getLogger(__name__)

__all__ = ["AuditTransport"]


class AuditTransport(httpx.AsyncBaseTransport):
    """Wrap an inner transport and emit one ``a2a.call`` per request."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        *,
        audit: AuditSink,
        tenant: str,
        subject: str,
        peer_id: str,
        target: str,
        agent_ref: AgentRef,
    ) -> None:
        self._inner = inner
        self._audit = audit
        self._tenant = tenant
        self._subject = subject
        self._peer_id = peer_id
        self._target = target
        self._agent_ref = agent_ref

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        invocation = current_invocation()
        context: Any = (
            a2a_span(invocation, target=self._target) if invocation is not None else nullcontext()
        )
        with context:
            started = time.perf_counter()
            try:
                response = await self._inner.handle_async_request(request)
            except Exception:
                await self._emit(request, "error", started)
                raise
            status: Literal["ok", "error"] = "ok" if response.status_code < 500 else "error"
            await self._emit(request, status, started)
            return response

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def _emit(
        self,
        request: httpx.Request,
        status: Literal["ok", "error"],
        started: float,
    ) -> None:
        invocation = current_invocation()
        trace_id = invocation.trace_id if invocation is not None else uuid.uuid4().hex
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=uuid.uuid4().hex,
            trace_id=trace_id,
            tenant=self._tenant,
            principal=Principal(tenant=self._tenant, subject=self._subject, kind="service"),
            agent_ref=self._agent_ref,
            action="a2a.call",
            target=self._target,
            args_hash=hash_text(f"{request.method} {request.url.path}"),
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="third_party",
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await self._audit.emit(event)
        except Exception:
            logger.exception("a2a egress audit emit failed")
