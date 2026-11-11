"""Policy-enforcing model gateway with audit."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from ..core import (
    AuditEvent,
    AuditSink,
    Invocation,
    ModelPolicy,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)


class ModelDenied(Exception):
    """The request is not allowed by the agent's model policy."""


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_messages(request: ModelRequest) -> str:
    payload = json.dumps(
        [message.model_dump() for message in request.messages],
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hash_text(payload)


class PolicyModelGateway:
    """Check the provider allowlist, call the provider, and audit the outcome."""

    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        audit: AuditSink | None = None,
    ) -> None:
        for name, provider in providers.items():
            if name != provider.name:
                raise ValueError(
                    f"provider key {name!r} does not match provider.name {provider.name!r}"
                )
        self.providers = dict(providers)
        self.audit = audit

    async def complete(
        self,
        invocation: Invocation,
        request: ModelRequest,
        policy: ModelPolicy,
    ) -> ModelResponse:
        started = time.perf_counter()
        if request.provider not in policy.provider_allowlist:
            await self._audit(
                invocation,
                request,
                status="denied",
                error_code="provider_not_allowed",
                egress="none",
                started=started,
            )
            raise ModelDenied(f"provider {request.provider!r} is not allowed by policy")

        provider = self.providers.get(request.provider)
        if provider is None:
            await self._audit(
                invocation,
                request,
                status="denied",
                error_code="provider_unavailable",
                egress="none",
                started=started,
            )
            raise ModelDenied(f"provider {request.provider!r} is not configured")

        try:
            response = await provider.complete(request)
        except Exception as exc:
            await self._audit(
                invocation,
                request,
                status="error",
                error_code=type(exc).__name__,
                egress=provider.egress,
                started=started,
            )
            raise

        await self._audit(
            invocation,
            request,
            status="ok",
            error_code=None,
            egress=provider.egress,
            started=started,
            response=response,
        )
        return response

    async def _audit(
        self,
        invocation: Invocation,
        request: ModelRequest,
        *,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        egress: Literal["none", "third_party"],
        started: float,
        response: ModelResponse | None = None,
    ) -> None:
        if self.audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            tenant=invocation.principal.tenant,
            principal=invocation.principal,
            agent_ref=invocation.agent_ref,
            action="model.call",
            target=f"{request.provider}:{request.model}",
            args_hash=_hash_messages(request),
            result_hash=_hash_text(response.text) if response is not None else None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens=(
                response.input_tokens + response.output_tokens if response is not None else None
            ),
            cost_usd=response.cost_usd if response is not None else None,
            egress=egress,
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)
