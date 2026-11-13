"""Policy-enforcing model gateway with audit."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Literal

from ..audit.hashing import hash_json, hash_text
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


class ModelUnavailable(RuntimeError):
    """The provider's circuit is open, so the call was not attempted."""


def egress_for(provider: str) -> Literal["none", "third_party"]:
    return "none" if provider == "vllm" else "third_party"


def check_provider(provider: str, policy: ModelPolicy) -> None:
    if provider not in policy.provider_allowlist:
        raise ModelDenied(f"provider {provider!r} is not allowed by policy")


def hash_messages(request: ModelRequest) -> str:
    return hash_json([message.model_dump() for message in request.messages])


async def emit_model_audit(
    audit: AuditSink | None,
    invocation: Invocation,
    *,
    provider: str,
    model: str,
    args_hash: str,
    result_hash: str | None,
    tokens: int | None,
    cost_usd: float | None,
    egress: Literal["none", "third_party"],
    status: Literal["ok", "error", "denied"],
    error_code: str | None,
    started: float,
) -> None:
    if audit is None:
        return
    event = AuditEvent(
        event_id=uuid.uuid4().hex,
        run_id=invocation.run_id,
        trace_id=invocation.trace_id,
        tenant=invocation.principal.tenant,
        principal=invocation.principal,
        agent_ref=invocation.agent_ref,
        action="model.call",
        target=f"{provider}:{model}",
        args_hash=args_hash,
        result_hash=result_hash,
        data_classes=[],
        latency_ms=int((time.perf_counter() - started) * 1000),
        tokens=tokens,
        cost_usd=cost_usd,
        egress=egress,
        status=status,
        error_code=error_code,
        timestamp=datetime.now(timezone.utc),
    )
    await audit.emit(event)


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
        args_hash = hash_messages(request)
        try:
            check_provider(request.provider, policy)
        except ModelDenied:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress="none",
                status="denied",
                error_code="provider_not_allowed",
                started=started,
            )
            raise

        provider = self.providers.get(request.provider)
        if provider is None:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress="none",
                status="denied",
                error_code="provider_unavailable",
                started=started,
            )
            raise ModelDenied(f"provider {request.provider!r} is not configured")

        try:
            response = await provider.complete(request)
        except Exception as exc:
            await emit_model_audit(
                self.audit,
                invocation,
                provider=request.provider,
                model=request.model,
                args_hash=args_hash,
                result_hash=None,
                tokens=None,
                cost_usd=None,
                egress=provider.egress,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
            raise

        await emit_model_audit(
            self.audit,
            invocation,
            provider=request.provider,
            model=request.model,
            args_hash=args_hash,
            result_hash=hash_text(response.text),
            tokens=response.input_tokens + response.output_tokens,
            cost_usd=response.cost_usd,
            egress=provider.egress,
            status="ok",
            error_code=None,
            started=started,
        )
        return response
